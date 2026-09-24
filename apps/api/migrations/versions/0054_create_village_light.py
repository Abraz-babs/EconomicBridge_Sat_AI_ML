"""village_light — measured night light and people at every real village.

WHY
---
Economic Visibility showed "poverty hotspots" at GENERATED points: two random
positions per LGA near its centre, named "<LGA> settlement N", with a
hash-derived population, a "households unreached by aid" figure that had no
source, and a poverty score that reduced to the darkness of the random point
(found 2026-09-24). This table replaces them with measurements at real places.

WHAT A ROW IS
-------------
One real GRID3 village (public.named_settlements, migration 0052) in one
measurement ROUND (`period`, a year): its NASA VIIRS Black Marble night light
as a 12-night median on clear dry-season nights and again in the wet season,
its class (unlit < 0.5, dim < 2, lit >= 2 nW/cm²/sr, dry season), and the
people and children under five living nearest to it within 1 km (Meta &
CIESIN HRSL, 30 m; each populated pixel counted once, at its nearest village).

Rounds are ADDED, never overwritten: (settlement_id, period) is unique, so the
2027 round sits beside 2026 and the platform can show which villages became
lit — electrification progress measured from space. Retention triggers (0051)
archive anything that is ever changed or removed.

Written by apps/ingestion/tasks/village_light_scan.py.

Revision ID: 0054
Revises: 0053
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0054"
down_revision: Union[str, Sequence[str], None] = "0053"
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
            CREATE TABLE IF NOT EXISTS "{schema}".village_light (
                id              BIGSERIAL PRIMARY KEY,
                settlement_id   BIGINT       NOT NULL,
                name            TEXT         NOT NULL,
                ward            TEXT,
                lga             TEXT,
                geom            geometry(Point, 4326) NOT NULL,
                period          TEXT         NOT NULL,
                radiance_dry    DOUBLE PRECISION,
                radiance_wet    DOUBLE PRECISION,
                light_class     TEXT         NOT NULL,
                light_class_wet TEXT,
                people          INTEGER      NOT NULL DEFAULT 0,
                under5          INTEGER      NOT NULL DEFAULT 0,
                dry_window      TEXT,
                wet_window      TEXT,
                sources         TEXT         NOT NULL,
                measured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (settlement_id, period)
            )
        """)
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_village_light_period ON "{schema}".village_light (period, light_class)')
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_village_light_lga ON "{schema}".village_light (lga)')
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_village_light_geom ON "{schema}".village_light USING GIST (geom)')
        for trigger, when in (
            ("retain_deleted_row", f'AFTER DELETE ON "{schema}".village_light FOR EACH ROW'),
            ("retain_overwritten_row", f'AFTER UPDATE ON "{schema}".village_light FOR EACH ROW '
                                       "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
        ):
            op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{schema}".village_light')
            op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # Measurements are records; keep the tables, drop only the triggers.
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP TRIGGER IF EXISTS retain_deleted_row ON "{schema}".village_light')
        op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".village_light')
