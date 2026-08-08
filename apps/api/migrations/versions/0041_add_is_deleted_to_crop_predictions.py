"""Soft delete for crop_predictions, so a bad or test diagnosis can be retired.

The recent-predictions feed is append-only and had no way to remove a row, so
test uploads and mistaken photos accumulate in the operator's list and in the
Disease Geography map forever.

Soft, not hard (CLAUDE.md §4.4): the row is flagged and stays auditable. That
matters more than usual here — an abstention is a record of an image the model
could not handle, which is exactly the retraining material we need. Deleting it
from the operator's view must not delete it from the evidence.

Mirrors migration 0034 (farm_checks).

Revision ID: 0041
Revises: 0040
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, Sequence[str], None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
        )
        # The feed always filters on this, so index it with created_at — the
        # ordering the recent-predictions query uses.
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_crop_predictions_live '
            f'ON "{schema}".crop_predictions (is_deleted, created_at DESC)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP INDEX IF EXISTS "{schema}".idx_crop_predictions_live')
        op.execute(
            f'ALTER TABLE "{schema}".crop_predictions '
            f"DROP COLUMN IF EXISTS is_deleted"
        )
