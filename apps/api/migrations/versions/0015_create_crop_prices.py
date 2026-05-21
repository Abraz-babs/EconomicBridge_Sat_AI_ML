"""create public.crop_prices for Module 04 — market price correlation

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-21

Module 04 (CropGuard) needs market price intelligence so smallholder
farmers know what to plant. Prices are regional (state-level for
Nigeria, country-level for ECOWAS tenants) but not strictly tenant-
isolated — the same maize price in Kaduna is the same number whether
the dashboard is viewed under tenant kaduna or fct. Living in
`public` (CLAUDE.md §4.2 — cross-tenant table) keeps inserts cheap.

Source provenance is mandatory on every row so the operator can later
flip seed rows for live NBS / FAOSTAT data without re-architecting:

  source='seed_v1'     — populated by scripts/seed_crop_prices.py
  source='nbs_fpw'     — NBS Food Price Watch monthly bulletin
  source='faostat'     — FAO Food Price Database
  source='amis'        — AMIS — Agricultural Market Information System

The UNIQUE constraint allows multiple sources for the same
(crop, region, date) so the operator can ship live data alongside
seed without a destructive migration.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.crop_prices (
            id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            crop               VARCHAR(40)  NOT NULL,
            region             VARCHAR(60)  NOT NULL,
            observed_at        DATE         NOT NULL,
            price_ngn_per_kg   DOUBLE PRECISION NOT NULL
                CHECK (price_ngn_per_kg > 0),
            source             VARCHAR(40)  NOT NULL,
            created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_crop_prices_observation
                UNIQUE (crop, region, observed_at, source)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crop_prices_crop_date "
        "ON public.crop_prices (crop, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crop_prices_region_date "
        "ON public.crop_prices (region, observed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.crop_prices CASCADE")
