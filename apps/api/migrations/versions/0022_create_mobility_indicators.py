"""create per-tenant mobility_indicators table (Slice 07 — Module 06)

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-23

Module 06 — Economic Mobility Compass. Per-LGA cost-of-living and
income-opportunity indicators that resettlement agencies + displaced
households use to compare destination options across pilot regions.

One row per (tenant_id, lga, source). The cost-of-living index is
expressed as a multiplier where 100 = the national/regional average,
so cross-tenant comparison reads cleanly:
  FCT  ~ 150 (capital premium)
  Kebbi ~  78 (rural northern Nigeria)
  Lagos (when added) ~ 165
  Ghana ~ 108 (national-level average via GHS-pegged proxy)

Real NBS API + ECOWAS STAT ingestion swaps in by writing rows with
source='nbs_col_v1' / 'ecowas_stat_v1' alongside the seed_v1 rows
the seed script populates.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".mobility_indicators (
            id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                   VARCHAR(50) NOT NULL,
            lga                         TEXT NOT NULL,
            location                    GEOMETRY(POINT, 4326) NOT NULL,

            -- Cost-of-living index where 100 = national reference.
            -- 0 to 300 covers extreme rural to extreme capital premium.
            cost_of_living_index        DOUBLE PRECISION NOT NULL
                CHECK (cost_of_living_index BETWEEN 0 AND 300),

            -- Mean household income, NGN/month. ECOWAS tenants converted
            -- via current XOF/GHS rates at ingest time.
            avg_household_income_ngn    INTEGER NOT NULL
                CHECK (avg_household_income_ngn >= 0),

            -- Composite score 0..1 — higher = more job opportunities
            -- relative to population (formal employment + informal).
            income_opportunity_score    DOUBLE PRECISION NOT NULL
                CHECK (income_opportunity_score BETWEEN 0 AND 1),

            -- Composite 0..1 — how suitable for receiving displaced
            -- populations (housing capacity, services, security).
            displacement_capacity_index DOUBLE PRECISION NOT NULL
                CHECK (displacement_capacity_index BETWEEN 0 AND 1),

            -- Pop estimate inherited from WorldPop where available.
            population                  INTEGER NOT NULL DEFAULT 0,

            observed_at                 DATE NOT NULL,
            source                      VARCHAR(40) NOT NULL,
                -- 'seed_v1' | 'nbs_col_v1' | 'ecowas_stat_v1' | 'iom_dtm_v1'
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_{tenant}_mobility_lga_source
                UNIQUE (tenant_id, lga, source)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_mobility_col '
        f'ON "{schema}".mobility_indicators (cost_of_living_index DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_mobility_location '
        f'ON "{schema}".mobility_indicators USING GIST (location)'
    )


def _drop_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".mobility_indicators CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_for(tenant)
