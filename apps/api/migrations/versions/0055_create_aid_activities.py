"""aid_activities — real aid activity, published by the organisations themselves.

WHY
---
Aid Coordination served invented coverage in every tenant (found 2026-09-24):
seed rows naming Mercy Corps, NEMA, Oxfam, Save the Children, UNHCR and UNICEF
in LGAs, with made-up beneficiary counts, and a "100% coverage" that was true
by construction because only LGAs with rows were counted. The first real source
(HDX HAPI operational presence, 0019/`hapi_v1`) covers north-east Nigeria only
and still returns nothing for any pilot.

WHAT A ROW IS
-------------
One published location of one IATI activity that was in implementation and
current when fetched (apps/ingestion/tasks/aid_iati_ingest.py): the reporting
organisation, title, sectors (OECD DAC names + overlap buckets), dates, the
coordinate as published, and where it lands — `lga` for a real site inside the
tenant, NULL for statewide activity (a state-labelled or state-centre location;
for Ghana / Senegal, countrywide). National programmes are not stored for a
state.

Rows are ADDED and updated only when the published record changes; nothing is
deleted, so an activity that ends stays as history and the API shows only
those current today. Retention triggers (0051) archive every earlier version.
The seed rows in aid_coverage are left in place (no record is deleted) and are
no longer read.

Revision ID: 0055
Revises: 0054
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0055"
down_revision: Union[str, Sequence[str], None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".aid_activities (
                id              BIGSERIAL PRIMARY KEY,
                iati_id         TEXT         NOT NULL,
                org_name        TEXT         NOT NULL,
                org_ref         TEXT,
                org_slug        TEXT         NOT NULL,
                title           TEXT,
                sectors         TEXT         NOT NULL DEFAULT '',
                sector_buckets  TEXT[]       NOT NULL DEFAULT '{{}}',
                lga             TEXT,
                location_name   TEXT,
                lon             DOUBLE PRECISION NOT NULL,
                lat             DOUBLE PRECISION NOT NULL,
                start_date      DATE,
                end_date        DATE,
                source          TEXT         NOT NULL DEFAULT 'iati_v1',
                first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (iati_id, lon, lat)
            )
        """)
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_aid_activities_dates ON "{schema}".aid_activities (end_date, start_date)')
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_aid_activities_lga ON "{schema}".aid_activities (lga)')
        for trigger, when in (
            ("retain_deleted_row", f'AFTER DELETE ON "{schema}".aid_activities FOR EACH ROW'),
            ("retain_overwritten_row", f'AFTER UPDATE ON "{schema}".aid_activities FOR EACH ROW '
                                       "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
        ):
            op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{schema}".aid_activities')
            op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # Records are kept; drop only the triggers.
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP TRIGGER IF EXISTS retain_deleted_row ON "{schema}".aid_activities')
        op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".aid_activities')
