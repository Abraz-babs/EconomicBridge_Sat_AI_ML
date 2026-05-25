"""create per-tenant skills_indicators table (Slice 08 — Module 07)

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-25

Module 07 — SkillsBridge. Per-LGA education + connectivity profile that
ministries of education and partners (UNICEF GIGA, ITU) use to identify
where digital learning infrastructure should land next.

One row per (tenant_id, lga, source). Coverage percentages are stored
as floats 0..100 so the dashboard reads them without further scaling.
Real GIGA / ITU ingestion swaps in by writing rows with source values
like 'giga_v1' / 'itu_v1' alongside the seed_v1 rows.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
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
        CREATE TABLE IF NOT EXISTS "{schema}".skills_indicators (
            id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                   VARCHAR(50) NOT NULL,
            lga                         TEXT NOT NULL,
            location                    GEOMETRY(POINT, 4326) NOT NULL,

            -- Total schools in the LGA (primary + secondary combined).
            school_count                INTEGER NOT NULL
                CHECK (school_count >= 0),

            -- Schools per 10k people. UNICEF GIGA benchmark ~ 4 per 10k
            -- for primary, ~ 1.5 for secondary in developed regions.
            school_density_per_10k      DOUBLE PRECISION NOT NULL
                CHECK (school_density_per_10k >= 0),

            -- % of population with reliable internet (mobile or fixed).
            internet_coverage_pct       DOUBLE PRECISION NOT NULL
                CHECK (internet_coverage_pct BETWEEN 0 AND 100),

            -- % of population covered by 2G+ mobile.
            mobile_coverage_pct         DOUBLE PRECISION NOT NULL
                CHECK (mobile_coverage_pct BETWEEN 0 AND 100),

            -- Grid uptime proxy 0..1 — relevant for in-school digital
            -- learning kits that need reliable power.
            electricity_reliability     DOUBLE PRECISION NOT NULL
                CHECK (electricity_reliability BETWEEN 0 AND 1),

            -- Under-18 population estimate (WorldPop demographic layer).
            youth_population            INTEGER NOT NULL DEFAULT 0,

            -- Composite 0..1 — HIGHER = WORSE (bigger digital learning gap).
            -- Weights: 0.4 internet, 0.3 schools, 0.3 electricity.
            learning_gap_index          DOUBLE PRECISION NOT NULL
                CHECK (learning_gap_index BETWEEN 0 AND 1),

            observed_at                 DATE NOT NULL,
            source                      VARCHAR(40) NOT NULL,
                -- 'seed_v1' | 'giga_v1' | 'itu_v1' | 'fme_v1'
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_{tenant}_skills_lga_source
                UNIQUE (tenant_id, lga, source)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_skills_gap '
        f'ON "{schema}".skills_indicators (learning_gap_index DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_skills_location '
        f'ON "{schema}".skills_indicators USING GIST (location)'
    )


def _drop_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".skills_indicators CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_for(tenant)
