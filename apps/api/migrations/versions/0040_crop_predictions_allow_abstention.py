"""Let crop_predictions record that the model DECLINED to name a disease.

The classifier can now abstain: when the operator declares a crop and the model
puts almost none of its confidence on that crop's classes, it returns no class
at all rather than a confident wrong answer (MIN_CROP_MASS in
apps/ml/models/crop_classifier.py, calibrated 2026-08-08).

`predicted_class` was `VARCHAR(80) NOT NULL` from migration 0014, so the first
real abstention in production — a maize field photo in Kebbi — inserted NULL and
returned a 500 to the dashboard. The guard worked; the table underneath it had
not been told.

Abstentions are WORTH STORING, not worth discarding: they are precisely the
images the model cannot handle, which makes them the retraining set we actually
need. So the column becomes nullable and two columns are added to say why.

Revision ID: 0040
Revises: 0039
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0040"
down_revision: Union[str, Sequence[str], None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same list migration 0014 used to create the tables.
PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ALTER COLUMN predicted_class DROP NOT NULL"
        )
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ADD COLUMN IF NOT EXISTS abstained BOOLEAN NOT NULL DEFAULT FALSE"
        )
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ADD COLUMN IF NOT EXISTS abstain_reason TEXT"
        )
        # A row must not be able to claim both an answer and a refusal, nor
        # neither. Enforced here rather than in the service so a future writer
        # cannot reintroduce the ambiguity.
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ADD CONSTRAINT chk_crop_predictions_abstention "
            f"CHECK ((abstained AND predicted_class IS NULL) "
            f"     OR (NOT abstained AND predicted_class IS NOT NULL))"
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"DROP CONSTRAINT IF EXISTS chk_crop_predictions_abstention"
        )
        # Abstained rows have no class to restore, so they are removed before
        # the NOT NULL goes back on — the alternative is inventing a label.
        op.execute(
            f'DELETE FROM "{schema}".crop_predictions WHERE predicted_class IS NULL'
        )
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"DROP COLUMN IF EXISTS abstain_reason"
        )
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"DROP COLUMN IF EXISTS abstained"
        )
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ALTER COLUMN predicted_class SET NOT NULL"
        )
