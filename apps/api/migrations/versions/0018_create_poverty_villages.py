"""create per-tenant poverty_villages table (Slice 01.real)

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-21

Module 01 — Poverty Mapping / Economic Visibility. Identified
vulnerable settlements per tenant ROI. Sourced from VIIRS Black
Marble nightlight (dim cluster → likely under-electrified, often
poor) + WorldPop population grid + DHS Survey validation samples.

For now rows ship from a deterministic seed script
(scripts/seed_poverty_villages.py) tagged `source='seed_v1'`; real
VIIRS/WorldPop ingestion follows the same schema with
`source='viirs_v2'` etc.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants on this
migration so we don't have to chase nasarawa later.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_poverty_villages_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".poverty_villages (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Identity
            settlement_name         TEXT NOT NULL,
            lga                     TEXT NOT NULL,

            -- Spatial
            location                GEOMETRY(POINT, 4326) NOT NULL,

            -- Metrics
            poverty_score           DOUBLE PRECISION NOT NULL
                CHECK (poverty_score BETWEEN 0 AND 1),
            population              INTEGER NOT NULL
                CHECK (population >= 0),
            households_unreached    INTEGER NOT NULL
                CHECK (households_unreached >= 0),
            nightlight_dimness      DOUBLE PRECISION NOT NULL
                CHECK (nightlight_dimness BETWEEN 0 AND 1),
            has_dhs_data            BOOLEAN NOT NULL DEFAULT FALSE,

            -- Real-source provenance (NULL when seeded)
            viirs_pixel_radiance    DOUBLE PRECISION,
            worldpop_estimate       DOUBLE PRECISION,

            -- Audit
            source                  VARCHAR(40) NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_{tenant}_poverty_settlement_lga
                UNIQUE (tenant_id, lga, settlement_name, source)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_poverty_villages_score '
        f'ON "{schema}".poverty_villages (poverty_score DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_poverty_villages_lga '
        f'ON "{schema}".poverty_villages (lga)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_poverty_villages_location '
        f'ON "{schema}".poverty_villages USING GIST (location)'
    )


def _drop_poverty_villages_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".poverty_villages CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_poverty_villages_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_poverty_villages_for(tenant)
