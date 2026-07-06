"""add owner_name to per-tenant farm_checks (farm / farmer full name)

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-06

Adds an optional owner_name column so a saved Farm Check carries the full name
of the farm owner alongside the coordinate, LGA and satellite reading — full
record of who + where + what the satellite saw. Additive and nullable, so
existing records and the crop-agnostic "general" checks are unaffected.

Per-tenant schema (CLAUDE.md §4.2); mirrors migration 0030.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, Sequence[str], None] = "0032"
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
            f"ADD COLUMN IF NOT EXISTS owner_name TEXT"
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(
            f'ALTER TABLE "tenant_{tenant}".farm_checks '
            f"DROP COLUMN IF EXISTS owner_name"
        )
