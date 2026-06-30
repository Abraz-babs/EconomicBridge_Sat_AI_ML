"""create per-tenant crop_health table (CropGuard statewide per-LGA NDVI health)

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-30

One row per LGA holding its CURRENT crop/vegetation health from Sentinel-2 NDVI
(healthy / moderate / stressed / poor / bare), so the CropGuard map can show
EVERY LGA of every tenant — not only the points a user uploaded a leaf photo for.
Derived (for free) from the per-LGA NDVI the Farmland encroachment sweep already
fetches; refreshed per LGA on the Sentinel revisit. Disease *diagnosis* stays the
leaf-photo / Farm Check layer on top (satellite shows WHERE stress is, a photo
shows WHAT the disease is).

Per-tenant schema (CLAUDE.md §4.2); all 10 pilots here, new tenants inherit via
services/tenant_provision.py (LIKE … INCLUDING ALL).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, Sequence[str], None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_crop_health_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".crop_health (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(50) NOT NULL,
            location        GEOMETRY(POINT, 4326) NOT NULL,
            lat             DOUBLE PRECISION NOT NULL,
            lon             DOUBLE PRECISION NOT NULL,
            lga             TEXT NOT NULL,
            ndvi            DOUBLE PRECISION,
            ndvi_date       DATE,
            health          VARCHAR(20) NOT NULL,
            verdict         TEXT NOT NULL DEFAULT '',
            source          VARCHAR(60) NOT NULL DEFAULT 'crop_health_v1',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_{tenant}_crop_health CHECK (health IN
                ('healthy', 'moderate', 'stressed', 'poor', 'bare', 'unknown'))
        )
        """
    )
    # One current row per LGA — the sweep deletes+reinserts on refresh.
    op.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS uq_{tenant}_crop_health_lga '
        f'ON "{schema}".crop_health (lga)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_crop_health_location '
        f'ON "{schema}".crop_health USING GIST (location)'
    )


def _drop_crop_health_for(tenant: str) -> None:
    op.execute(f'DROP TABLE IF EXISTS "tenant_{tenant}".crop_health CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_crop_health_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_crop_health_for(tenant)
