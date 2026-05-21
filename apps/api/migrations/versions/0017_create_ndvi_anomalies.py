"""create per-tenant ndvi_anomalies table (Slice 04.d)

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-21

Pre-symptomatic disease detection via NDVI anomaly: when a 14-day
window of vegetation index drops > 1.5σ below the same calendar
window's 3-year baseline, we record an anomaly event with the
projected disease probability. Operator triggers a scan via
POST /api/v1/cropguard/ndvi/scan; results land here for audit.

Algorithm is statistical (z-score), not learned — table is in API
service not ML. If/when we add an autoencoder-based detector the
schema absorbs the model_version + features fields cleanly.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_ndvi_anomalies_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".ndvi_anomalies (
            id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id           VARCHAR(50) NOT NULL,

            -- Detection identity
            detector_name       VARCHAR(80) NOT NULL,
            detector_version    VARCHAR(50) NOT NULL,

            -- Time window
            window_start        DATE NOT NULL,
            window_end          DATE NOT NULL,

            -- Metrics
            ndvi_recent_mean    DOUBLE PRECISION NOT NULL
                CHECK (ndvi_recent_mean BETWEEN 0 AND 1),
            ndvi_baseline_mean  DOUBLE PRECISION NOT NULL
                CHECK (ndvi_baseline_mean BETWEEN 0 AND 1),
            ndvi_baseline_std   DOUBLE PRECISION NOT NULL
                CHECK (ndvi_baseline_std >= 0),
            z_score             DOUBLE PRECISION NOT NULL,
            -- 0..1 projected disease probability — derived from |z|
            -- (no learned model yet, statistical projection only).
            disease_probability DOUBLE PRECISION NOT NULL
                CHECK (disease_probability BETWEEN 0 AND 1),
            anomaly             BOOLEAN NOT NULL,
            confidence_band     VARCHAR(10) NOT NULL,

            -- Optional crop hint (when scan is crop-specific)
            crop                VARCHAR(40),

            -- Optional spatial context
            location            GEOMETRY(POINT, 4326),
            lga                 TEXT,
            zone_name           TEXT,

            -- Audit
            trace_id            UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_ndvi_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW')),
            CONSTRAINT chk_{tenant}_ndvi_window_order
                CHECK (window_start <= window_end)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_ndvi_anomalies_created '
        f'ON "{schema}".ndvi_anomalies (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_ndvi_anomalies_anomaly '
        f'ON "{schema}".ndvi_anomalies (anomaly, created_at DESC) '
        f'WHERE anomaly = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_ndvi_anomalies_window '
        f'ON "{schema}".ndvi_anomalies (window_end DESC, window_start DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_ndvi_anomalies_location '
        f'ON "{schema}".ndvi_anomalies USING GIST (location)'
    )


def _drop_ndvi_anomalies_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".ndvi_anomalies CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_ndvi_anomalies_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_ndvi_anomalies_for(tenant)
