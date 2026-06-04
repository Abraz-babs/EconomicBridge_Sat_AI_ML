"""scheduled report subscriptions

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-04

A super-admin subscribes a recipient to a tenant+module report on a cadence
(monthly / quarterly). A scheduled job (scripts/send_scheduled_reports.py)
generates the PDF and emails it, then stamps last_sent_at. Public schema — the
registry is platform-wide, not per-tenant.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, Sequence[str], None] = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.report_subscriptions (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(50) NOT NULL,
            module          VARCHAR(40) NOT NULL,
            frequency       VARCHAR(20) NOT NULL DEFAULT 'monthly',
            recipient_email TEXT NOT NULL,
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            last_sent_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_report_sub_frequency
                CHECK (frequency IN ('monthly', 'quarterly')),
            CONSTRAINT uq_report_sub
                UNIQUE (tenant_id, module, recipient_email, frequency)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_sub_due "
        "ON public.report_subscriptions (enabled, last_sent_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.report_subscriptions")
