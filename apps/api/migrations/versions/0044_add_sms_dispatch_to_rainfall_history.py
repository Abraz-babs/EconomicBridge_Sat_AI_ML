"""Record whether a rainfall advisory was sent to farmers, and to how many.

Automatic farmer SMS needs an idempotency anchor that survives everything: a
re-run of the scan, a redeploy mid-dispatch, a task that dies after the gateway
accepted the message but before it could record that. Without one, the failure
mode is not a missing message but a REPEATED one — the same advisory landing on
a farmer's phone every morning until the weather changes, which is how a
service people trust becomes one they block.

`rainfall_advisory_history` already carries UNIQUE (lga, observed_date), so it
is exactly the right place: one advisory per LGA per rainfall day, therefore at
most one SMS batch per LGA per rainfall day. Marking the row is the commit
point.

`sms_recipients` is kept alongside because "we advised Argungu on 18 Aug and it
reached 11 people" is the sentence an insurer, a prize jury or a state ministry
actually wants, and reconstructing it later from sms_outbox joins is work we
would rather not owe ourselves.

Both columns are nullable: NULL means "not dispatched", which is the correct
reading for every row written before this migration.

Revision ID: 0044
Revises: 0043
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044"
down_revision: Union[str, Sequence[str], None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(
            f'ALTER TABLE "{schema}".rainfall_advisory_history '
            f"ADD COLUMN IF NOT EXISTS sms_dispatched_at TIMESTAMPTZ"
        )
        op.execute(
            f'ALTER TABLE "{schema}".rainfall_advisory_history '
            f"ADD COLUMN IF NOT EXISTS sms_recipients INTEGER"
        )
        # Partial index on the undispatched rows: the dispatcher's only query is
        # "what have we not sent yet", and that set stays small while the table
        # grows for the life of the pilot.
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_rain_hist_undispatched '
            f'ON "{schema}".rainfall_advisory_history (advised_at DESC) '
            f"WHERE sms_dispatched_at IS NULL"
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP INDEX IF EXISTS "{schema}".idx_rain_hist_undispatched')
        # Dropping these loses the record of what was already sent, so a
        # re-upgrade would re-send every historical advisory. Kept explicit
        # rather than silent: only downgrade with farmer SMS disabled.
        op.execute(
            f'ALTER TABLE "{schema}".rainfall_advisory_history '
            f"DROP COLUMN IF EXISTS sms_recipients"
        )
        op.execute(
            f'ALTER TABLE "{schema}".rainfall_advisory_history '
            f"DROP COLUMN IF EXISTS sms_dispatched_at"
        )
