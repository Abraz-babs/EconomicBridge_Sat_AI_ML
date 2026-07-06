"""add is_deleted to per-tenant farm_checks (soft delete for saved records)

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-06

Operators need to remove wrong/unwanted saved Farm Checks (e.g. a mistyped
coordinate) — but records are audit data, so deletion is SOFT (CLAUDE.md §4.4):
a flag hides the row from recall while the observation itself is preserved.
Additive and defaulted, so existing rows are unaffected.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0034"
down_revision: Union[str, Sequence[str], None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(
            f'ALTER TABLE "tenant_{tenant}".farm_checks '
            f"ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(
            f'ALTER TABLE "tenant_{tenant}".farm_checks '
            f"DROP COLUMN IF EXISTS is_deleted"
        )
