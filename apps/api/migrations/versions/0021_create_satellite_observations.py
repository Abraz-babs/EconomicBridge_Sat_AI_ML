"""create per-tenant satellite_observations table (Slice 05.live)

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-22

Daily time series of satellite-derived aggregate metrics per tenant ROI.
Populated by the Sentinel Hub Statistical API → Module 05 ShockGuard
flood/drought detectors + Module 04 CropGuard NDVI anomaly detector
read from here when data_source='live' is requested.

One row per (tenant_id, observed_at, dataset, source) tuple. Columns
cover the three signals the detectors need:

  sar_backscatter_db   — Sentinel-1 GRD VV mean in dB (flood input)
  ndvi_mean            — Sentinel-2 L2A NDVI mean (drought + NDVI anomaly input)
  lst_anomaly_c        — MODIS LST anomaly °C (drought input — Phase B)

Each signal lives in its own column rather than a generic "value" so
queries stay simple (SELECT ndvi_mean FROM ... WHERE tenant_id=...).
Nullable because not every (date, tenant) has every signal — SAR fires
every 6 days, S2 every 5 days, MODIS LST is daily.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_satellite_observations_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".satellite_observations (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Identity of the observation
            observed_at             DATE NOT NULL,
            dataset                 VARCHAR(40) NOT NULL,
                -- 'sentinel-1-grd' | 'sentinel-2-l2a' | 'modis-lst'

            -- Per-signal aggregates (nullable per signal; only one is
            -- expected non-null per row in the common case)
            sar_backscatter_db      DOUBLE PRECISION,
            ndvi_mean               DOUBLE PRECISION,
            lst_anomaly_c           DOUBLE PRECISION,

            -- Provenance + sample size
            sample_count            INTEGER NOT NULL DEFAULT 0,
            stat_min                DOUBLE PRECISION,
            stat_max                DOUBLE PRECISION,
            stat_std                DOUBLE PRECISION,

            -- Audit
            source                  VARCHAR(40) NOT NULL,
                -- 'sentinel_stat_v1' (live) | 'detector_v1' (synthetic) | …
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_{tenant}_satellite_obs
                UNIQUE (tenant_id, observed_at, dataset, source)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_sat_obs_date '
        f'ON "{schema}".satellite_observations (observed_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_sat_obs_dataset '
        f'ON "{schema}".satellite_observations (dataset, observed_at DESC)'
    )


def _drop_satellite_observations_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".satellite_observations CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_satellite_observations_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_satellite_observations_for(tenant)
