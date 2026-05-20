"""create per-tenant crop_predictions table (Q2 CropGuard)

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-20

The ML service emits one row per crop-disease inference (ResNet-50,
apps/ml/models/crop_classifier.py). Schema mirrors conflict_predictions
(migration 0005) — same ModelPrediction contract (CLAUDE.md §9) — but
swaps the spatial/zone columns for crop-specific ones:

  predicted_class       Top-1 class label from the 12-class set
  top_k                 JSONB array of {class_name, probability} for
                        the top-K (K = settings.crop_top_k_classes,
                        default 3) — UI shows runner-up diseases too.
  image_source          's3' | 'inline' — provenance for audit
  image_s3_key          Bucket-relative key when image_source='s3'.
                        NULL for inline (base64) submissions.
  image_sha256          SHA-256 of the input image bytes — replayable.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants get the table
on this migration so we don't have to chase nasarawa with a follow-up
like we did for conflict_predictions (see migrations 0008 / 0012).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_crop_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".crop_predictions (
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
            confidence_band         VARCHAR(10) NOT NULL,
            requires_human_review   BOOLEAN NOT NULL DEFAULT FALSE,

            -- Class output
            predicted_class         VARCHAR(80) NOT NULL,
            -- Top-K leaderboard: JSONB array of (class_name, probability) pairs,
            -- highest probability first. See ml.models.crop_classifier for shape.
            top_k                   JSONB NOT NULL,

            -- Input image provenance
            image_source            VARCHAR(10) NOT NULL,  -- 's3' | 'inline'
            image_s3_bucket         VARCHAR(120),
            image_s3_key            TEXT,
            image_sha256            VARCHAR(64) NOT NULL,

            -- Optional location of the field/farm — set when caller knows it
            location                GEOMETRY(POINT, 4326),
            lga                     TEXT,
            zone_name               TEXT,

            -- Audit
            inference_time_ms       INTEGER,
            trace_id                UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_crop_confidence_band
                CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW')),
            CONSTRAINT chk_{tenant}_crop_image_source
                CHECK (image_source IN ('s3', 'inline'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_crop_predictions_created '
        f'ON "{schema}".crop_predictions (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_crop_predictions_class '
        f'ON "{schema}".crop_predictions (predicted_class, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_crop_predictions_review '
        f'ON "{schema}".crop_predictions (requires_human_review, created_at DESC) '
        f'WHERE requires_human_review = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_crop_predictions_location '
        f'ON "{schema}".crop_predictions USING GIST (location)'
    )


def _drop_crop_predictions_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".crop_predictions CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_crop_predictions_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_crop_predictions_for(tenant)
