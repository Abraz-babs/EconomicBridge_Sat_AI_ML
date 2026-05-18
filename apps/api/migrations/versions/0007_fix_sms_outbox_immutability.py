"""replace recursive sms_outbox UPDATE rule with a BEFORE UPDATE trigger

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18

Migration 0006 created a rule:

    CREATE RULE sms_outbox_no_update AS ON UPDATE TO public.sms_outbox
    DO INSTEAD UPDATE public.sms_outbox SET status = NEW.status, ...
    WHERE id = OLD.id

That pattern recurses forever — the DO INSTEAD UPDATE fires the same rule
again. Postgres detects this at prepare time:

    asyncpg.exceptions.InvalidObjectDefinitionError:
      infinite recursion detected in rules for relation "sms_outbox"

The intent ("allow lifecycle columns to advance, block changes to identity
+ content + audit columns") is correctly expressed with a row trigger that
compares OLD vs NEW per column and raises if a forbidden column changed.

We KEEP the existing DELETE rule (DO INSTEAD NOTHING) — that one cannot
recurse and enforces audit immutability per CLAUDE.md s4.6.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP RULE IF EXISTS sms_outbox_no_update ON public.sms_outbox")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.sms_outbox_enforce_immutable_columns()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.id                    IS DISTINCT FROM OLD.id
            OR NEW.tenant_id             IS DISTINCT FROM OLD.tenant_id
            OR NEW.subscriber_id         IS DISTINCT FROM OLD.subscriber_id
            OR NEW.phone_e164            IS DISTINCT FROM OLD.phone_e164
            OR NEW.message               IS DISTINCT FROM OLD.message
            OR NEW.language              IS DISTINCT FROM OLD.language
            OR NEW.related_prediction_id IS DISTINCT FROM OLD.related_prediction_id
            OR NEW.related_alert_id      IS DISTINCT FROM OLD.related_alert_id
            OR NEW.severity              IS DISTINCT FROM OLD.severity
            OR NEW.alert_type            IS DISTINCT FROM OLD.alert_type
            OR NEW.provider              IS DISTINCT FROM OLD.provider
            OR NEW.queued_at             IS DISTINCT FROM OLD.queued_at
            OR NEW.trace_id              IS DISTINCT FROM OLD.trace_id
            THEN
                RAISE EXCEPTION
                    'sms_outbox row % is immutable for identity/content columns', OLD.id
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_sms_outbox_immutable
        BEFORE UPDATE ON public.sms_outbox
        FOR EACH ROW
        EXECUTE FUNCTION public.sms_outbox_enforce_immutable_columns()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sms_outbox_immutable ON public.sms_outbox")
    op.execute("DROP FUNCTION IF EXISTS public.sms_outbox_enforce_immutable_columns()")
