"""widen alert_events.alert_type to include 'fire'

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-19

Phase A.1 — connect NASA FIRMS to the dashboard.

The chk_alert_events_alert_type constraint (migration 0003) allows only
{conflict, flood, crop_disease, drought}. FIRMS-derived alerts don't fit
any of those — they're fire-pixel detections from MODIS / VIIRS.

This migration replaces the constraint with one that adds 'fire'. Run on
every existing tenant schema (the 9 from 0002 + nasarawa from 0008).

`DROP CONSTRAINT IF EXISTS` keeps it idempotent so re-runs are safe.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_SCHEMAS: tuple[str, ...] = (
    "tenant_kebbi",
    "tenant_benue",
    "tenant_plateau",
    "tenant_kaduna",
    "tenant_niger",
    "tenant_zamfara",
    "tenant_fct",
    "tenant_ghana",
    "tenant_senegal",
    "tenant_nasarawa",
)

NEW_ALERT_TYPES = ("conflict", "flood", "crop_disease", "drought", "fire")
OLD_ALERT_TYPES = ("conflict", "flood", "crop_disease", "drought")


def _types_in_clause(types: tuple[str, ...]) -> str:
    return ", ".join(f"'{t}'" for t in types)


def upgrade() -> None:
    for schema in TENANT_SCHEMAS:
        op.execute(
            f'ALTER TABLE "{schema}".alert_events '
            f"DROP CONSTRAINT IF EXISTS chk_alert_events_alert_type"
        )
        op.execute(
            f'ALTER TABLE "{schema}".alert_events '
            f"ADD CONSTRAINT chk_alert_events_alert_type "
            f"CHECK (alert_type IN ({_types_in_clause(NEW_ALERT_TYPES)}))"
        )


def downgrade() -> None:
    # Wipe any 'fire' rows before restoring the narrower constraint, otherwise
    # the CHECK addition fails. Soft-delete rather than hard-delete so the
    # audit trail of FIRMS-derived alerts survives.
    for schema in TENANT_SCHEMAS:
        op.execute(
            f'UPDATE "{schema}".alert_events SET is_deleted = TRUE '
            f"WHERE alert_type = 'fire' AND NOT is_deleted"
        )
        op.execute(
            f'ALTER TABLE "{schema}".alert_events '
            f"DROP CONSTRAINT IF EXISTS chk_alert_events_alert_type"
        )
        op.execute(
            f'ALTER TABLE "{schema}".alert_events '
            f"ADD CONSTRAINT chk_alert_events_alert_type "
            f"CHECK (alert_type IN ({_types_in_clause(OLD_ALERT_TYPES)}))"
        )
