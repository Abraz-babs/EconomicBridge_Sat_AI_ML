"""tenant registry + per-tenant module entitlements

Super-admin provisioning model: tenants are registered (after MoU/subscription)
into public.tenant_registry, and their accessible modules are controlled via
public.tenant_modules. The dashboard nav + an API middleware read these so a
tenant only sees/uses the modules under their jurisdiction or subscription.

Both tables live in `public` (cross-tenant control plane). Seeded for the 10
pilots by scripts/seed_tenant_registry.py (all modules enabled, so existing
behaviour is unchanged until a super-admin toggles something off).

Idempotent (IF NOT EXISTS) so re-runs are safe.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tenant_registry (
            id                  VARCHAR(50) PRIMARY KEY,
            name                TEXT NOT NULL,
            tenant_type         VARCHAR(30) NOT NULL DEFAULT 'ng_state',
            country             VARCHAR(40) NOT NULL DEFAULT 'nigeria',
            status              VARCHAR(20) NOT NULL DEFAULT 'active',
            mou_reference       TEXT,
            subscription_tier   VARCHAR(30) NOT NULL DEFAULT 'standard',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_tenant_registry_status
                CHECK (status IN ('provisioning', 'active', 'suspended'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tenant_modules (
            tenant_id   VARCHAR(50) NOT NULL,
            module_key  VARCHAR(40) NOT NULL,
            enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, module_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_modules_tenant "
        "ON public.tenant_modules (tenant_id) WHERE enabled = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.tenant_modules")
    op.execute("DROP TABLE IF EXISTS public.tenant_registry")
