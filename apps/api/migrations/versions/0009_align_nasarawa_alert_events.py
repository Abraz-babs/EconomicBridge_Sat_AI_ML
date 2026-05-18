"""align tenant_nasarawa.alert_events with the canonical 0003 shape

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18

Migration 0008 created tenant_nasarawa from a leaner template and missed seven
columns that the AlertEvent ORM (and migration 0003 for the original 9 pilots)
declares: `boundary`, `model_input_hash`, `shap_values`, `reviewed_by`,
`reviewed_at`, `reviewer_notes`, `created_by`. SELECT *-style queries against
the new schema 500'd because asyncpg saw "column alert_events.boundary does
not exist."

This migration brings tenant_nasarawa into parity. `ADD COLUMN IF NOT EXISTS`
keeps it idempotent. The 3 seed rows are untouched (the new columns all
default to NULL).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "tenant_nasarawa"
TABLE = f'"{SCHEMA}".alert_events'


def upgrade() -> None:
    for ddl in (
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS boundary GEOMETRY(POLYGON, 4326)",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS model_input_hash VARCHAR(64)",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS shap_values JSONB",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS reviewed_by UUID",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS reviewer_notes TEXT",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS created_by UUID",
    ):
        op.execute(ddl)


def downgrade() -> None:
    # Drop in reverse order. CLAUDE.md §13 says "never drop a column" in normal
    # operations — this downgrade only exists for the test-suite teardown path
    # and is safe because nothing depends on these columns yet.
    for col in (
        "created_by",
        "reviewer_notes",
        "reviewed_at",
        "reviewed_by",
        "shap_values",
        "model_input_hash",
        "boundary",
    ):
        op.execute(f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {col}")
