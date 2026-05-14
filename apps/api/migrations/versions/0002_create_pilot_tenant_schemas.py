"""provision pilot tenant schemas

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-12

Creates a Postgres schema per pilot tenant (the 6 Phase-1 Nigerian states +
FCT + the first two ECOWAS pilots) so the TenantContext middleware has
something to `SET search_path` into.

Each schema gets a minimal `widgets` test table. This is intentionally
placeholder data — the real per-tenant tables (alert_events,
satellite_observations, etc.) will be created by later migrations as each
module's data model lands. The widgets table exists so we can integration-
test cross-tenant isolation without having to seed the full tenant template.

Schema names must match `services.tenants.PILOT_TENANT_IDS` exactly.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi",
    "benue",
    "plateau",
    "kaduna",
    "niger",
    "zamfara",
    "fct",
    "ghana",
    "senegal",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        # Identifier — safe to interpolate because PILOT_TENANTS is a tuple
        # of compile-time string literals (no user input).
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".widgets (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(f'DROP SCHEMA IF EXISTS "tenant_{tenant}" CASCADE')
