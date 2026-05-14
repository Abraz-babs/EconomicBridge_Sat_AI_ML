"""drop widgets, create alert_events per pilot schema

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-14

Replaces the placeholder `widgets` smoke-test table (created in 0002) with the
real `alert_events` table — the first per-tenant production table.

Schema mirrors models.alert_event.AlertEvent and matches the pattern roughed
out in the legacy create_tenant_schema() function. PostGIS columns require the
`postgis` extension (already installed by 0001's guarded DO block).

Indexes are critical here because every pilot tenant will see ~thousands of
alerts/year:
  - (status, created_at DESC) — covers the default API query (recent active
    alerts) and uses the index for the ORDER BY
  - (severity)                 — filtering by severity
  - (alert_type)               — filtering by module
  - GIST(location)             — spatial range queries (map bounding box reads)
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi",
    "benue",
    "plateau",
    "kaduna",
    "niger",
    "zamfara",
    "fct",
    "ghana",
    "senegal",
)


def _create_alert_events_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    # All identifiers are compile-time constants — safe to interpolate.
    op.execute(f'DROP TABLE IF EXISTS "{schema}".widgets')
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".alert_events (
            id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                   VARCHAR(50) NOT NULL,

            alert_type                  VARCHAR(50) NOT NULL,
            severity                    VARCHAR(20) NOT NULL,
            status                      VARCHAR(30) NOT NULL DEFAULT 'pending_review',

            zone_name                   TEXT,
            lga                         TEXT,
            location                    GEOMETRY(POINT, 4326),
            boundary                    GEOMETRY(POLYGON, 4326),

            confidence_score            DOUBLE PRECISION
                CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
            affected_area_ha            DOUBLE PRECISION,
            livelihoods_at_risk         INTEGER,
            economic_value_ngn          DOUBLE PRECISION,
            predicted_breach_hours      INTEGER,

            satellite_source            TEXT,
            satellite_pass_time         TIMESTAMPTZ,
            model_name                  VARCHAR(100),
            model_version               VARCHAR(50),
            model_input_hash            VARCHAR(64),
            shap_values                 JSONB,

            human_review_required       BOOLEAN NOT NULL DEFAULT TRUE,
            reviewed_by                 UUID,
            reviewed_at                 TIMESTAMPTZ,
            reviewer_notes              TEXT,
            agencies_notified           TEXT[],

            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by                  UUID,

            CONSTRAINT chk_alert_events_severity
                CHECK (severity IN ('critical', 'high', 'medium', 'low')),
            CONSTRAINT chk_alert_events_status
                CHECK (status IN ('pending_review', 'acknowledged', 'resolved', 'dismissed')),
            CONSTRAINT chk_alert_events_alert_type
                CHECK (alert_type IN ('conflict', 'flood', 'crop_disease', 'drought'))
        )
        """
    )

    # Updated-at trigger — reuses the public.update_updated_at() function
    # created by migration 0001.
    op.execute(
        f"""
        CREATE TRIGGER trg_{tenant}_alert_events_updated_at
            BEFORE UPDATE ON "{schema}".alert_events
            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at()
        """
    )

    # Indexes
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_status_created '
        f'ON "{schema}".alert_events (status, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_severity '
        f'ON "{schema}".alert_events (severity)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_type '
        f'ON "{schema}".alert_events (alert_type)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_lga '
        f'ON "{schema}".alert_events (lga)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_location '
        f'ON "{schema}".alert_events USING GIST (location)'
    )
    # Partial index — `WHERE is_deleted = FALSE` is the API's default filter so
    # this covers the hot path and stays small.
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_alerts_active '
        f'ON "{schema}".alert_events (created_at DESC) WHERE is_deleted = FALSE'
    )


def _drop_alert_events_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".alert_events CASCADE')
    # Re-create the placeholder widgets table so the downgrade leaves the DB
    # in the state migration 0002 produced.
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".widgets (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_alert_events_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_alert_events_for(tenant)
