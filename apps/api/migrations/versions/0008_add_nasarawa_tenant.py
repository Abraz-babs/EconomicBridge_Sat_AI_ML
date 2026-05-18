"""add nasarawa state as 10th pilot tenant

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-18

Nasarawa State joins the active pilot roster as a Phase-1 priority — it sits
in Nigeria's Middle Belt and has a persistent record of Tiv-Fulani / herder-
farmer conflicts that the Farmland Protection module is explicitly designed
to address. Sourcing was previously parked for Phase 2 (see tenants.yaml);
field-team feedback elevated it.

This migration mirrors what 0002 + 0003 + 0004 + 0005 + 0006 did for the
original 9 pilots, scoped to the single new schema. The SQL is identical
to those migrations' per-tenant blocks so the resulting structure matches.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT = "nasarawa"
SCHEMA = f"tenant_{TENANT}"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    # ── alert_events (mirrors 0003) ──────────────────────────────────────
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{SCHEMA}".alert_events (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            alert_type              VARCHAR(50) NOT NULL,
            severity                VARCHAR(20) NOT NULL,
            status                  VARCHAR(30) NOT NULL DEFAULT 'pending_review',

            zone_name               TEXT,
            lga                     TEXT,
            location                GEOMETRY(POINT, 4326),

            confidence_score        DOUBLE PRECISION,
            affected_area_ha        DOUBLE PRECISION,
            livelihoods_at_risk     INTEGER,
            economic_value_ngn      DOUBLE PRECISION,
            predicted_breach_hours  INTEGER,

            satellite_source        TEXT,
            satellite_pass_time     TIMESTAMPTZ,

            model_name              VARCHAR(100),
            model_version           VARCHAR(50),
            human_review_required   BOOLEAN NOT NULL DEFAULT FALSE,
            agencies_notified       TEXT[],

            related_observation_id  UUID,
            trace_id                UUID,

            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{TENANT}_alert_severity
                CHECK (severity IN ('critical', 'high', 'medium', 'low')),
            CONSTRAINT chk_{TENANT}_alert_status
                CHECK (status IN ('pending_review', 'acknowledged', 'resolved', 'dismissed')),
            CONSTRAINT chk_{TENANT}_alert_type
                CHECK (alert_type IN ('conflict', 'flood', 'crop_disease', 'drought'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_alerts_created '
        f'ON "{SCHEMA}".alert_events (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_alerts_status '
        f'ON "{SCHEMA}".alert_events (status, severity, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_alerts_type '
        f'ON "{SCHEMA}".alert_events (alert_type, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_alerts_location '
        f'ON "{SCHEMA}".alert_events USING GIST (location)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_alerts_active '
        f'ON "{SCHEMA}".alert_events (severity, created_at DESC) '
        f'WHERE is_deleted = FALSE'
    )
    op.execute(
        f"CREATE TRIGGER trg_{TENANT}_alerts_updated_at "
        f'BEFORE UPDATE ON "{SCHEMA}".alert_events '
        f'FOR EACH ROW EXECUTE FUNCTION public.update_updated_at()'
    )

    # ── heat_signatures (mirrors 0004 per-tenant block) ──────────────────
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{SCHEMA}".heat_signatures (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,
            ingestion_run_id        UUID REFERENCES public.ingestion_runs(id) ON DELETE SET NULL,

            source                  VARCHAR(50) NOT NULL,
            acquisition_time        TIMESTAMPTZ NOT NULL,
            location                GEOMETRY(POINT, 4326) NOT NULL,

            brightness_kelvin       DOUBLE PRECISION,
            confidence              SMALLINT,
            frp_mw                  DOUBLE PRECISION,
            day_night               CHAR(1),
            satellite               VARCHAR(20),
            instrument              VARCHAR(20),

            raw_payload             JSONB,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{TENANT}_heat_daynight CHECK (day_night IN ('D', 'N') OR day_night IS NULL),
            CONSTRAINT chk_{TENANT}_heat_confidence CHECK (confidence BETWEEN 0 AND 100 OR confidence IS NULL)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_heat_acquisition '
        f'ON "{SCHEMA}".heat_signatures (acquisition_time DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_heat_source_time '
        f'ON "{SCHEMA}".heat_signatures (source, acquisition_time DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_heat_location '
        f'ON "{SCHEMA}".heat_signatures USING GIST (location)'
    )

    # ── conflict_predictions (mirrors 0005 per-tenant block) ─────────────
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{SCHEMA}".conflict_predictions (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            model_name              VARCHAR(100) NOT NULL,
            model_version           VARCHAR(50) NOT NULL,
            input_hash              VARCHAR(64) NOT NULL,

            prediction              DOUBLE PRECISION NOT NULL
                CHECK (prediction BETWEEN 0 AND 1),
            confidence              DOUBLE PRECISION NOT NULL
                CHECK (confidence BETWEEN 0 AND 1),
            confidence_band         VARCHAR(10) NOT NULL,
            requires_human_review   BOOLEAN NOT NULL DEFAULT FALSE,

            features                JSONB NOT NULL,
            shap_values             JSONB NOT NULL,
            shap_base_value         DOUBLE PRECISION,

            location                GEOMETRY(POINT, 4326),
            lga                     TEXT,
            zone_name               TEXT,

            related_alert_id        UUID REFERENCES "{SCHEMA}".alert_events(id) ON DELETE SET NULL,

            inference_time_ms       INTEGER,
            trace_id                UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{TENANT}_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_predictions_created '
        f'ON "{SCHEMA}".conflict_predictions (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_predictions_band '
        f'ON "{SCHEMA}".conflict_predictions (confidence_band, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_predictions_location '
        f'ON "{SCHEMA}".conflict_predictions USING GIST (location)'
    )

    # ── alert_subscribers (mirrors 0006 per-tenant block) ────────────────
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{SCHEMA}".alert_subscribers (
            id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                VARCHAR(50) NOT NULL,

            full_name                TEXT,
            phone_e164               VARCHAR(20) NOT NULL,
            language                 VARCHAR(5) NOT NULL DEFAULT 'en',

            lga                      TEXT,
            zone_name                TEXT,
            location                 GEOMETRY(POINT, 4326),

            severity_threshold       VARCHAR(20) NOT NULL DEFAULT 'high',
            alert_types              TEXT[],
            channel                  VARCHAR(20) NOT NULL DEFAULT 'sms',

            is_active                BOOLEAN NOT NULL DEFAULT TRUE,
            opted_in_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            opted_out_at             TIMESTAMPTZ,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{TENANT}_subscriber_severity
                CHECK (severity_threshold IN ('critical', 'high', 'medium', 'all')),
            CONSTRAINT chk_{TENANT}_subscriber_channel
                CHECK (channel IN ('sms', 'voice', 'whatsapp')),
            CONSTRAINT uq_{TENANT}_subscriber_phone_lga
                UNIQUE (phone_e164, lga)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_subscribers_lga '
        f'ON "{SCHEMA}".alert_subscribers (lga) WHERE is_active = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{TENANT}_subscribers_location '
        f'ON "{SCHEMA}".alert_subscribers USING GIST (location)'
    )
    op.execute(
        f"CREATE TRIGGER trg_{TENANT}_subscribers_updated_at "
        f'BEFORE UPDATE ON "{SCHEMA}".alert_subscribers '
        f'FOR EACH ROW EXECUTE FUNCTION public.update_updated_at()'
    )


def downgrade() -> None:
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
