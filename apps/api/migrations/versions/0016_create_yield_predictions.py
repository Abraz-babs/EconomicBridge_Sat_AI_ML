"""create per-tenant yield_predictions table (Slice 04.c)

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-21

The ML service (apps/ml) emits one row per yield inference (Random
Forest regressor, see apps/ml/models/yield_predictor.py). Schema
mirrors crop_predictions + conflict_predictions for audit consistency,
but the inference output is a continuous tons/hectare estimate
alongside the canonical [0..1] prediction score the dashboard reads.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants on this
migration so we don't have to chase nasarawa with a follow-up later.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_yield_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".yield_predictions (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Model identity
            model_name              VARCHAR(100) NOT NULL,
            model_version           VARCHAR(50) NOT NULL,
            input_hash              VARCHAR(64) NOT NULL,

            -- Canonical contract (CLAUDE.md §9) — score in [0..1]
            prediction              DOUBLE PRECISION NOT NULL
                CHECK (prediction BETWEEN 0 AND 1),
            confidence              DOUBLE PRECISION NOT NULL
                CHECK (confidence BETWEEN 0 AND 1),
            confidence_band         VARCHAR(10) NOT NULL,
            requires_human_review   BOOLEAN NOT NULL DEFAULT FALSE,

            -- Yield-specific output
            crop                    VARCHAR(40) NOT NULL,
            predicted_yield_t_ha    DOUBLE PRECISION NOT NULL
                CHECK (predicted_yield_t_ha >= 0),
            -- Lower/upper bound of a 80% prediction interval. NULL
            -- when the model didn't expose a PI (rare).
            yield_pi_low_t_ha       DOUBLE PRECISION,
            yield_pi_high_t_ha      DOUBLE PRECISION,

            -- Feature input (replayable + auditable)
            features                JSONB NOT NULL,
            shap_values             JSONB NOT NULL,
            shap_base_value         DOUBLE PRECISION,

            -- Optional spatial context
            location                GEOMETRY(POINT, 4326),
            lga                     TEXT,
            zone_name               TEXT,

            -- Audit
            inference_time_ms       INTEGER,
            trace_id                UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_yield_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW')),
            CONSTRAINT chk_{tenant}_yield_pi_order
                CHECK (
                    yield_pi_low_t_ha IS NULL OR yield_pi_high_t_ha IS NULL
                    OR yield_pi_low_t_ha <= yield_pi_high_t_ha
                )
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_yield_predictions_created '
        f'ON "{schema}".yield_predictions (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_yield_predictions_crop '
        f'ON "{schema}".yield_predictions (crop, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_yield_predictions_review '
        f'ON "{schema}".yield_predictions (requires_human_review, created_at DESC) '
        f'WHERE requires_human_review = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_yield_predictions_location '
        f'ON "{schema}".yield_predictions USING GIST (location)'
    )


def _drop_yield_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".yield_predictions CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_yield_predictions_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_yield_predictions_for(tenant)
