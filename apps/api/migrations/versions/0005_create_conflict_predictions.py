"""create per-tenant conflict_predictions table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-15

The ML service (apps/ml, port 8002) emits one row per inference. The table
captures the ModelPrediction contract from CLAUDE.md §9: model_version,
confidence, SHAP values, input_hash, and the human-review flag.

Per-tenant schema (CLAUDE.md §4.2). Created in every pilot tenant schema by
the loop in upgrade().
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal",
)


def _create_conflict_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".conflict_predictions (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Model identity
            model_name              VARCHAR(100) NOT NULL,
            model_version           VARCHAR(50) NOT NULL,
            input_hash              VARCHAR(64) NOT NULL,

            -- Inference output
            prediction              DOUBLE PRECISION NOT NULL
                CHECK (prediction BETWEEN 0 AND 1),
            confidence              DOUBLE PRECISION NOT NULL
                CHECK (confidence BETWEEN 0 AND 1),
            confidence_band         VARCHAR(10) NOT NULL,  -- HIGH | MEDIUM | LOW
            requires_human_review   BOOLEAN NOT NULL DEFAULT FALSE,

            -- Feature input (replayable + auditable)
            features                JSONB NOT NULL,
            shap_values             JSONB NOT NULL,
            shap_base_value         DOUBLE PRECISION,

            -- Location of the prediction (origin point or polygon centroid)
            location                GEOMETRY(POINT, 4326),
            lga                     TEXT,
            zone_name               TEXT,

            -- Optional linkage to the alert_events row this informed
            related_alert_id        UUID REFERENCES "{schema}".alert_events(id) ON DELETE SET NULL,

            -- Audit
            inference_time_ms       INTEGER,
            trace_id                UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_predictions_created '
        f'ON "{schema}".conflict_predictions (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_predictions_model '
        f'ON "{schema}".conflict_predictions (model_name, model_version)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_predictions_band '
        f'ON "{schema}".conflict_predictions (confidence_band, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_predictions_review '
        f'ON "{schema}".conflict_predictions (requires_human_review, created_at DESC) '
        f'WHERE requires_human_review = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_predictions_location '
        f'ON "{schema}".conflict_predictions USING GIST (location)'
    )


def _drop_conflict_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".conflict_predictions CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_conflict_predictions_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_conflict_predictions_for(tenant)
