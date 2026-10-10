"""lga_risk_profile + risk_overlay — the pre-season risk profile for insurers.

WHY
---
NAIC prices a season before planting. Approved 2026-10-10 (mock 2026-10-09):
every LGA gets a flood band, a drought band and a failed-rains band under one
published rule, with the figures behind each — farmland in the JRC river flood
zones, farmland under water in UNOSAT's satellite flood maps, 35 seasons of
CHIRPS rainfall, onsets, false starts and dry spells from daily rainfall since
1998, and the people and villages exposed.

WHAT A ROW IS
-------------
lga_risk_profile: one LGA in one ROUND, keyed by the last complete season the
round reads (`through_season`) and the method. The figures behind the bands are
JSONB (`figures`) so the page, the PDF and the CSV print the same numbers.

risk_overlay: the map layers of one round — farmland inside the 1-in-10-year
flood zone, and the water each satellite flood map saw — as small greyscale PNG
masks with the box they cover.

Rounds are ADDED, never overwritten: next year's round sits beside this one.
Retention triggers (0051) archive anything a re-run of the same round changes.

Written by apps/ingestion/tasks/risk_profile.py.

Revision ID: 0061
Revises: 0060
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0061"
down_revision: Union[str, Sequence[str], None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)
TABLES = ("lga_risk_profile", "risk_overlay")


def _retain(qualified: str) -> None:
    for trigger, when in (
        ("retain_deleted_row", f"AFTER DELETE ON {qualified} FOR EACH ROW"),
        ("retain_overwritten_row", f"AFTER UPDATE ON {qualified} FOR EACH ROW "
                                   "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {qualified}")
        op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".lga_risk_profile (
                id              BIGSERIAL PRIMARY KEY,
                lga             TEXT         NOT NULL,
                through_season  INTEGER      NOT NULL,
                method          TEXT         NOT NULL,
                band_flood      TEXT         NOT NULL,
                band_drought    TEXT         NOT NULL,
                band_rains      TEXT         NOT NULL,
                figures         JSONB        NOT NULL,
                sources         TEXT         NOT NULL,
                measured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (lga, through_season, method)
            )
        """)
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_lga_risk_profile_round '
                   f'ON "{schema}".lga_risk_profile (through_season, method)')
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".risk_overlay (
                id              BIGSERIAL PRIMARY KEY,
                through_season  INTEGER      NOT NULL,
                method          TEXT         NOT NULL,
                layer           TEXT         NOT NULL,
                label           TEXT         NOT NULL,
                west            DOUBLE PRECISION NOT NULL,
                south           DOUBLE PRECISION NOT NULL,
                east            DOUBLE PRECISION NOT NULL,
                north           DOUBLE PRECISION NOT NULL,
                width           INTEGER      NOT NULL,
                height          INTEGER      NOT NULL,
                png             BYTEA        NOT NULL,
                measured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (through_season, method, layer)
            )
        """)
        for table in TABLES:
            _retain(f'"{schema}".{table}')


def downgrade() -> None:
    # Measurements are records: keep the tables, drop only the triggers.
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for table in TABLES:
            op.execute(f'DROP TRIGGER IF EXISTS retain_deleted_row ON "{schema}".{table}')
            op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".{table}')
