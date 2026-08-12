"""Allow 'sns' as an sms_outbox provider.

`chk_sms_outbox_provider` was written in 0006 when the Nigerian gateway was
Termii: CHECK (provider IN ('termii', 'twilio', 'mock')). The Nigerian pilots
have since moved to AWS SNS (`services/providers.py` routes all eight NG
tenants to 'sns'), and `SnsGateway.name` is the string 'sns' — which that
CHECK rejects.

Nothing surfaced this because of how the failure lands. `_insert_outbox_row`
wraps the INSERT in `except IntegrityError` and treats it as an idempotency
collision, because 0026 added partial UNIQUE indexes that legitimately raise
IntegrityError for a genuine duplicate. A CHECK violation raises the same
Python exception, so a real SNS send would have been reported as
`skipped_duplicate` for every subscriber: no SMS, no error, no alarming log
line. The dispatcher is being taught to tell 23514 from 23505 alongside this
migration; widening the CHECK removes the cause.

Not caught earlier because SMS has only ever run against MockGateway
(`sms_sns_enabled` is still false in Terraform), and 'mock' passes the CHECK.

Revision ID: 0043
Revises: 0042
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0043"
down_revision: Union[str, Sequence[str], None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.sms_outbox DROP CONSTRAINT IF EXISTS chk_sms_outbox_provider"
    )
    op.execute(
        "ALTER TABLE public.sms_outbox ADD CONSTRAINT chk_sms_outbox_provider "
        "CHECK (provider IN ('termii', 'twilio', 'sns', 'mock'))"
    )


def downgrade() -> None:
    # Rows written while SNS was permitted would violate the old constraint, so
    # drop them out of the check rather than fail the downgrade. They stay in
    # the table: sms_outbox is an append-only audit log (0006/0007) and deleting
    # delivery history to satisfy a schema rollback would be the wrong trade.
    op.execute(
        "ALTER TABLE public.sms_outbox DROP CONSTRAINT IF EXISTS chk_sms_outbox_provider"
    )
    op.execute(
        "ALTER TABLE public.sms_outbox ADD CONSTRAINT chk_sms_outbox_provider "
        "CHECK (provider IN ('termii', 'twilio', 'mock')) NOT VALID"
    )
