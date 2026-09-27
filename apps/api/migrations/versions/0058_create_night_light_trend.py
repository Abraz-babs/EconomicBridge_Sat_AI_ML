"""Night-light trend — how much light each LGA and village shows, every year since 2012.

WHY
---
Mobility Compass showed per-LGA cost of living, income, opportunity and
capacity spread from one state-level anchor with deterministic noise
(withdrawn 2026-09-26). Its displacement rebuild was dropped because IOM DTM
counts are licensed for non-commercial use only. The rebuild approved on
2026-09-27 measures activity itself: the light NASA's satellites see at night,
every year since 2012, LGA by LGA and village by village — where towns and
markets are growing and where they are fading.

WHAT A ROW IS
-------------
lga_night_light: one LGA, one year, one of NASA Black Marble's two yearly
composites (VNP46A4 near-nadir and all-angle, snow-free): the summed radiance
over the LGA's pixels and the area lit at 1 nW/cm²/sr or more. Both
composites are kept because single years are noisy and the two sometimes
disagree; the module shows only changes both agree on.

village_light_trend: one GRID3 village (as measured in village_light, 0054)
with its yearly radiance series on both composites and a status —
gone_dark, newly_lit or steady — decided on both composites together.

Years are ADDED, never overwritten: (lga, year, composite) and
(settlement_id, last_year) are unique, so a new year adds rows beside the old
ones. Retention triggers (0051) keep anything a re-run changes.

Written by apps/ingestion/tasks/night_light_trend.py.

Revision ID: 0058
Revises: 0057
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0058"
down_revision: Union[str, Sequence[str], None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)
TABLES = ("lga_night_light", "village_light_trend")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".lga_night_light (
                id              BIGSERIAL PRIMARY KEY,
                lga             TEXT             NOT NULL,
                year            INTEGER          NOT NULL,
                composite       TEXT             NOT NULL,
                radiance_sum    DOUBLE PRECISION NOT NULL,
                lit_km2         DOUBLE PRECISION NOT NULL,
                pixels          INTEGER          NOT NULL,
                source          TEXT             NOT NULL,
                measured_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
                UNIQUE (lga, year, composite)
            )
        """)
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".village_light_trend (
                id              BIGSERIAL PRIMARY KEY,
                settlement_id   BIGINT       NOT NULL,
                name            TEXT         NOT NULL,
                ward            TEXT,
                lga             TEXT,
                geom            geometry(Point, 4326) NOT NULL,
                people          INTEGER      NOT NULL DEFAULT 0,
                first_year      INTEGER      NOT NULL,
                last_year       INTEGER      NOT NULL,
                near_nadir      REAL[]       NOT NULL,
                all_angle       REAL[]       NOT NULL,
                status          TEXT         NOT NULL,
                since_year      INTEGER,
                source          TEXT         NOT NULL,
                measured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (settlement_id, last_year)
            )
        """)
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_village_light_trend_status '
                   f'ON "{schema}".village_light_trend (last_year, status)')
        for table in TABLES:
            for trigger, when in (
                ("retain_deleted_row", f'AFTER DELETE ON "{schema}".{table} FOR EACH ROW'),
                ("retain_overwritten_row", f'AFTER UPDATE ON "{schema}".{table} FOR EACH ROW '
                                           "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
            ):
                op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{schema}".{table}')
                op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # Measurements are records; keep the tables, drop only the triggers.
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for table in TABLES:
            op.execute(f'DROP TRIGGER IF EXISTS retain_deleted_row ON "{schema}".{table}')
            op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".{table}')
