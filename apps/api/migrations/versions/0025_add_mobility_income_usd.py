"""add avg_household_income_usd to mobility_indicators (Module 06 dual-currency)

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-29

Module 06 goes multi-country for the ECOWAS pilot. Income is now captured in
USD as the cross-country comparable (World Bank NY.GNP.PCAP.CD — native per
country, no FX guesswork), alongside the existing NGN value for Nigeria.

The dashboard shows `₦X ($Y)` for Nigerian tenants and `$Y` for Ghana/Senegal.

Nullable: existing rows (seed_v1, worldbank_v1) predate USD capture, and the
ECOWAS tenants have no NGN value — each row carries whichever currencies apply.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _add_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f'ALTER TABLE "{schema}".mobility_indicators '
        f"ADD COLUMN IF NOT EXISTS avg_household_income_usd INTEGER "
        f"CHECK (avg_household_income_usd >= 0)"
    )
    # ECOWAS (Ghana/Senegal) rows carry USD only — no Naira value — so the
    # NGN column must allow NULL. Each row now holds whichever currency applies.
    op.execute(
        f'ALTER TABLE "{schema}".mobility_indicators '
        f"ALTER COLUMN avg_household_income_ngn DROP NOT NULL"
    )


def _drop_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    # Backfill any NULL NGN before restoring the NOT NULL constraint so the
    # downgrade can't fail on ECOWAS rows.
    op.execute(
        f'UPDATE "{schema}".mobility_indicators '
        f"SET avg_household_income_ngn = 0 WHERE avg_household_income_ngn IS NULL"
    )
    op.execute(
        f'ALTER TABLE "{schema}".mobility_indicators '
        f"ALTER COLUMN avg_household_income_ngn SET NOT NULL"
    )
    op.execute(
        f'ALTER TABLE "{schema}".mobility_indicators '
        f"DROP COLUMN IF EXISTS avg_household_income_usd"
    )


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _add_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_for(tenant)
