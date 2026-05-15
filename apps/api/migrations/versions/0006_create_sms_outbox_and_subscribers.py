"""create sms_outbox (public) + alert_subscribers (per-tenant)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-15

Step 10 — Termii SMS alerts. Adds two tables:

* `public.sms_outbox` — append-only audit of every SMS dispatch attempt (real
  via Termii / Twilio, or mock in dev when no provider key is configured).
  Cross-tenant by design so operators can survey the whole programme. Marked
  INSERT-only at the application layer via the same convention as `audit_log`.

* `tenant_<id>.alert_subscribers` — phone numbers that opted in to alerts
  for a given LGA and severity threshold. Per-tenant because subscriber
  rosters are sovereign-state data (NDPA 2023 + ECOWAS equivalents).

Provider strings come from a closed set so reporting queries can group cleanly
(`termii`, `twilio`, `mock`). Status strings ditto (`queued`, `sent`,
`delivered`, `failed`, `mock`).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal",
)


def _create_alert_subscribers_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".alert_subscribers (
            id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                VARCHAR(50) NOT NULL,

            full_name                TEXT,
            phone_e164               VARCHAR(20) NOT NULL,
            language                 VARCHAR(5) NOT NULL DEFAULT 'en',

            -- Where this subscriber wants to be alerted
            lga                      TEXT,
            zone_name                TEXT,
            location                 GEOMETRY(POINT, 4326),

            -- Severity threshold: 'critical' (only critical), 'high' (high+critical), 'all'
            severity_threshold       VARCHAR(20) NOT NULL DEFAULT 'high',

            -- Which alert types this subscriber wants
            -- conflict | flood | crop_disease | drought (NULL or empty = all)
            alert_types              TEXT[],

            -- Channel preference: 'sms' | 'voice' | 'whatsapp' (only SMS today)
            channel                  VARCHAR(20) NOT NULL DEFAULT 'sms',

            -- Audit
            is_active                BOOLEAN NOT NULL DEFAULT TRUE,
            opted_in_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            opted_out_at             TIMESTAMPTZ,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_subscriber_severity
                CHECK (severity_threshold IN ('critical', 'high', 'medium', 'all')),
            CONSTRAINT chk_{tenant}_subscriber_channel
                CHECK (channel IN ('sms', 'voice', 'whatsapp')),
            CONSTRAINT uq_{tenant}_subscriber_phone_lga
                UNIQUE (phone_e164, lga)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_subscribers_lga '
        f'ON "{schema}".alert_subscribers (lga) WHERE is_active = TRUE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_subscribers_active '
        f'ON "{schema}".alert_subscribers (is_active, opted_in_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_subscribers_location '
        f'ON "{schema}".alert_subscribers USING GIST (location)'
    )
    op.execute(
        f"CREATE TRIGGER trg_{tenant}_subscribers_updated_at "
        f'BEFORE UPDATE ON "{schema}".alert_subscribers '
        f'FOR EACH ROW EXECUTE FUNCTION public.update_updated_at()'
    )


def _drop_alert_subscribers_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".alert_subscribers CASCADE')


def upgrade() -> None:
    # ── public.sms_outbox ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.sms_outbox (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Who and what
            subscriber_id           UUID,
            phone_e164              VARCHAR(20) NOT NULL,
            message                 TEXT NOT NULL,
            language                VARCHAR(5) NOT NULL DEFAULT 'en',

            -- Source of the dispatch (which prediction or alert triggered it)
            related_prediction_id   UUID,
            related_alert_id        UUID,
            severity                VARCHAR(20),
            alert_type              VARCHAR(50),

            -- Provider + lifecycle
            provider                VARCHAR(20) NOT NULL,
            provider_message_id     TEXT,
            status                  VARCHAR(20) NOT NULL DEFAULT 'queued',
            error_message           TEXT,

            -- Cost / accounting (Termii NGN per segment)
            cost_units              DOUBLE PRECISION,
            cost_currency           VARCHAR(8),

            -- Audit
            trace_id                UUID,
            queued_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            dispatched_at           TIMESTAMPTZ,
            delivered_at            TIMESTAMPTZ,

            CONSTRAINT chk_sms_outbox_provider
                CHECK (provider IN ('termii', 'twilio', 'mock')),
            CONSTRAINT chk_sms_outbox_status
                CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'mock'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sms_outbox_tenant_queued "
        "ON public.sms_outbox (tenant_id, queued_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sms_outbox_status "
        "ON public.sms_outbox (status) WHERE status IN ('queued', 'failed')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sms_outbox_prediction "
        "ON public.sms_outbox (related_prediction_id) "
        "WHERE related_prediction_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sms_outbox_phone "
        "ON public.sms_outbox (phone_e164, queued_at DESC)"
    )

    # INSERT-only — matches the audit_log convention (CLAUDE.md §4.6).
    op.execute(
        "CREATE RULE sms_outbox_no_update AS ON UPDATE TO public.sms_outbox "
        "DO INSTEAD UPDATE public.sms_outbox SET "
        "  status = NEW.status, "
        "  provider_message_id = NEW.provider_message_id, "
        "  error_message = NEW.error_message, "
        "  dispatched_at = NEW.dispatched_at, "
        "  delivered_at = NEW.delivered_at, "
        "  cost_units = NEW.cost_units, "
        "  cost_currency = NEW.cost_currency "
        "WHERE id = OLD.id"
    )
    op.execute(
        "CREATE RULE sms_outbox_no_delete AS ON DELETE TO public.sms_outbox "
        "DO INSTEAD NOTHING"
    )

    # ── tenant_<id>.alert_subscribers ──────────────────────────────────
    for tenant in PILOT_TENANTS:
        _create_alert_subscribers_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_alert_subscribers_for(tenant)
    op.execute("DROP TABLE IF EXISTS public.sms_outbox CASCADE")
