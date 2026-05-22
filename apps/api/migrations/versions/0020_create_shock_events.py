"""create per-tenant shock_events table (Slice 05 — ShockGuard)

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-21

Module 05 — ShockGuard: 48-hour flood + drought early warning.

  flood   detection: Sentinel-1 SAR backscatter anomaly. Open water
                     has dramatically lower radar backscatter than dry
                     soil/vegetation — a sudden drop over a known land
                     area is the canonical flood signal.
  drought detection: MODIS thermal + NDVI composite. Sustained surface
                     temperature anomaly + NDVI decline against the
                     5-year same-window baseline triggers an alert.

For now rows ship from a statistical detector over a synthetic
backscatter / thermal series (services/shock_detector.py) tagged
`source='detector_v1'`; real U-Net flood segmentation on
Sentinel-1 GRD geotiffs lands in a follow-up slice with the same
schema (source flips to `sentinel1_unet_v1`).

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants on this
migration so we don't have to chase nasarawa later.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_shock_events_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".shock_events (
            id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                VARCHAR(50) NOT NULL,

            -- Event identity
            event_type               VARCHAR(20) NOT NULL,    -- 'flood' | 'drought'
            detector_name            VARCHAR(80) NOT NULL,
            detector_version         VARCHAR(50) NOT NULL,

            -- Severity ramp + confidence band (CLAUDE.md §9 alignment).
            severity                 VARCHAR(20) NOT NULL,    -- low/medium/high/critical
            confidence               DOUBLE PRECISION NOT NULL
                CHECK (confidence BETWEEN 0 AND 1),
            confidence_band          VARCHAR(10) NOT NULL,    -- HIGH/MEDIUM/LOW
            requires_human_review    BOOLEAN NOT NULL DEFAULT TRUE,

            -- Lead time — how many hours before expected onset.
            projected_onset_hours    INTEGER NOT NULL DEFAULT 0,

            -- Geometric scope
            affected_area_km2        DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (affected_area_km2 >= 0),
            population_at_risk       INTEGER NOT NULL DEFAULT 0
                CHECK (population_at_risk >= 0),
            location                 GEOMETRY(POINT, 4326),
            lga                      TEXT,
            zone_name                TEXT,

            -- Detector-specific metrics. For flood: backscatter delta dB.
            -- For drought: thermal anomaly °C + NDVI delta.
            metrics                  JSONB NOT NULL,

            -- Audit
            source                   VARCHAR(40) NOT NULL,
            trace_id                 UUID,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_shock_event_type
                CHECK (event_type IN ('flood', 'drought')),
            CONSTRAINT chk_{tenant}_shock_severity
                CHECK (severity IN ('low', 'medium', 'high', 'critical')),
            CONSTRAINT chk_{tenant}_shock_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_shock_events_created '
        f'ON "{schema}".shock_events (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_shock_events_severity '
        f'ON "{schema}".shock_events (severity, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_shock_events_type '
        f'ON "{schema}".shock_events (event_type, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_shock_events_location '
        f'ON "{schema}".shock_events USING GIST (location)'
    )


def _drop_shock_events_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".shock_events CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_shock_events_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_shock_events_for(tenant)
