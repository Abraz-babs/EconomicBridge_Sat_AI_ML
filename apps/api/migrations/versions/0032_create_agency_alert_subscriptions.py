"""create public.agency_alert_subscriptions (government-agency email alerts)

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-30

A responsible government agency subscribes (by email) to the alerts that relate
to its duty for a given tenant + module:
  * shockguard → disaster agencies (NEMA / state SEMA): flood / drought
  * farmland   → security / agriculture: encroachment & land-disturbance
  * cropguard  → agriculture: crop stress

A scheduled (or admin-triggered) digest emails each agency the NEW relevant
alerts at/above its severity threshold since `last_notified_at`, in English.
Public schema — a cross-tenant registry like report_subscriptions (migration
0029). SMS is a separate, deferred channel.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, Sequence[str], None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.agency_alert_subscriptions (
            id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            agency_name         VARCHAR(160) NOT NULL,
            recipient_email     TEXT NOT NULL,
            tenant_id           VARCHAR(50) NOT NULL,
            module              VARCHAR(40) NOT NULL,
            severity_threshold  VARCHAR(20) NOT NULL DEFAULT 'high',
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            last_notified_at    TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_agency_alert_module
                CHECK (module IN ('farmland', 'shockguard', 'cropguard')),
            CONSTRAINT chk_agency_alert_severity
                CHECK (severity_threshold IN ('critical', 'high', 'medium', 'all')),
            CONSTRAINT uq_agency_alert_sub
                UNIQUE (tenant_id, module, recipient_email)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agency_alert_active "
        "ON public.agency_alert_subscriptions (is_active, tenant_id, module)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.agency_alert_subscriptions CASCADE")
