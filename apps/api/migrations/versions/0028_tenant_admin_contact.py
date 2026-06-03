"""add admin contact to tenant_registry (onboarding invites)

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-03

Tenant onboarding: when a super-admin registers a tenant, the system creates an
organisation + a tenant-admin user and emails them a one-time activation link.
We record the contact the invite was sent to on the registry row itself, so the
admin matrix can show "invited / activated" without joining users.

`admin_email` is nullable because the 10 seeded pilots predate onboarding (they
have no invited contact). New registrations always set it.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, Sequence[str], None] = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant_registry ADD COLUMN IF NOT EXISTS admin_email TEXT")
    op.execute("ALTER TABLE public.tenant_registry ADD COLUMN IF NOT EXISTS admin_name TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE public.tenant_registry DROP COLUMN IF EXISTS admin_name")
    op.execute("ALTER TABLE public.tenant_registry DROP COLUMN IF EXISTS admin_email")
