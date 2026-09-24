"""Retain every record: archive each deleted row (and each overwritten season
measure) instead of letting it vanish.

WHY
---
Directed by the operator on 2026-09-24: "NO RECORD SHOULD GO — RETAIN ALL WE
HAVE." Until now several scheduled jobs erased rows as part of refreshing them:

* the daily encroachment sweep deleted an LGA's pending watches on every read,
  and replaced its crop-health reading by DELETE + INSERT;
* the land-change scan deleted each LGA's previous land-change alerts and
  hotspots before writing the new ones (55 alerts replaced by 62 on 2026-09-23);
* the ShockGuard and storm scans delete and rewrite their shock_events;
* price and poverty loads delete their previous row sets.

The records were real, and once deleted they survived only in the 7-day RDS
backup window.

HOW
---
One archive table, `public.deleted_records`, and one trigger function. An
AFTER DELETE row trigger on every table a job deletes from copies the old row
into the archive as JSONB before it is gone. The season-vegetation measure is
also covered AFTER UPDATE, because its upsert overwrites the previous figures
in place.

Deliberately a database-level net rather than a change to each detector:
* no detector, API or panel behaves differently — the live view is untouched;
* it catches every path, including manual SQL and the seed scripts;
* JSONB, not a column-for-column copy, so a later ALTER TABLE on any source
  table can never make the trigger fail and take a pipeline down with it.

Rows are archived in the same transaction as the delete: a rolled-back delete
leaves no archive row, and a committed one always has its copy.

`downgrade()` removes the triggers and function but NEVER drops the archive —
dropping it would destroy exactly what this migration exists to keep.

Revision ID: 0051
Revises: 0050
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0051"
down_revision: Union[str, Sequence[str], None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)

# Per-tenant tables that any job or script deletes from.
TENANT_TABLES: tuple[str, ...] = (
    "alert_events", "land_change_hotspots", "shock_events", "crop_health",
    "poverty_villages", "aid_coverage", "crop_predictions",
    "mobility_indicators", "skills_indicators", "lga_season_vegetation",
)
# Upserted in place: the previous figures are overwritten, so keep them too.
UPDATE_TABLES: tuple[str, ...] = ("lga_season_vegetation",)
PUBLIC_TABLES: tuple[str, ...] = ("crop_prices",)

TRIGGER = "retain_deleted_row"
UPDATE_TRIGGER = "retain_overwritten_row"


def _attach(schema: str, table: str, *, on_update: bool) -> None:
    """Attach the trigger(s) if the table exists in this schema — not every
    tenant has every table, and a missing one must not fail the migration."""
    qualified = f'"{schema}".{table}'
    update_ddl = (
        f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER} ON {qualified}; "
        f"CREATE TRIGGER {UPDATE_TRIGGER} AFTER UPDATE ON {qualified} "
        f"FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) "
        f"EXECUTE FUNCTION public.retain_old_row();"
    ) if on_update else ""
    op.execute(f"""
        DO $body$
        BEGIN
            IF to_regclass('{qualified}') IS NOT NULL THEN
                DROP TRIGGER IF EXISTS {TRIGGER} ON {qualified};
                CREATE TRIGGER {TRIGGER} AFTER DELETE ON {qualified}
                    FOR EACH ROW EXECUTE FUNCTION public.retain_old_row();
                {update_ddl}
            END IF;
        END
        $body$;
    """)


def _detach(schema: str, table: str) -> None:
    qualified = f'"{schema}".{table}'
    op.execute(f"""
        DO $body$
        BEGIN
            IF to_regclass('{qualified}') IS NOT NULL THEN
                DROP TRIGGER IF EXISTS {TRIGGER} ON {qualified};
                DROP TRIGGER IF EXISTS {UPDATE_TRIGGER} ON {qualified};
            END IF;
        END
        $body$;
    """)


def upgrade() -> None:
    # CREATE TRIGGER takes a lock that conflicts with open writes on the table.
    # Fail fast rather than queue: a queued DDL lock blocks every later writer
    # behind it, which would stall the live services until the migration ran.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.deleted_records (
            id           BIGSERIAL PRIMARY KEY,
            schema_name  TEXT        NOT NULL,
            table_name   TEXT        NOT NULL,
            operation    TEXT        NOT NULL,
            row_data     JSONB       NOT NULL,
            archived_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_deleted_records_source
            ON public.deleted_records (schema_name, table_name, archived_at)
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.retain_old_row() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
            INSERT INTO public.deleted_records
                (schema_name, table_name, operation, row_data)
            VALUES (TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP, to_jsonb(OLD));
            RETURN NULL;
        END
        $fn$
    """)
    for tenant in PILOT_TENANTS:
        for table in TENANT_TABLES:
            _attach(f"tenant_{tenant}", table, on_update=table in UPDATE_TABLES)
    for table in PUBLIC_TABLES:
        _attach("public", table, on_update=False)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        for table in TENANT_TABLES:
            _detach(f"tenant_{tenant}", table)
    for table in PUBLIC_TABLES:
        _detach("public", table)
    op.execute("DROP FUNCTION IF EXISTS public.retain_old_row()")
    # public.deleted_records is kept on purpose — see the module docstring.
