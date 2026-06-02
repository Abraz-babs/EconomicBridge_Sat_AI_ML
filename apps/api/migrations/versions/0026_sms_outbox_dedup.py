"""sms_outbox per-event dedup (partial unique indexes)

The dispatcher catches IntegrityError and reports `skipped_duplicate`, but no
UNIQUE constraint existed — so the same alert/prediction could be dispatched to
the same subscriber more than once (e.g. auto-notify + a manual send, or a
re-acknowledged farmland alert). This adds the partial unique indexes that make
that dedup real:

  * (related_alert_id, subscriber_id)      WHERE related_alert_id IS NOT NULL
  * (related_prediction_id, subscriber_id) WHERE related_prediction_id IS NOT NULL

Ad-hoc dispatches (both ids NULL) are intentionally not deduped. Note: each
ShockGuard *scan* persists a NEW event id, so this dedups re-sends of the SAME
event — not two scans of the same flood (that needs event-identity dedup at the
detector, tracked separately).

Idempotent (IF NOT EXISTS) so re-runs are safe.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0026"
down_revision: Union[str, Sequence[str], None] = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sms_outbox_alert_subscriber "
        "ON public.sms_outbox (related_alert_id, subscriber_id) "
        "WHERE related_alert_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sms_outbox_prediction_subscriber "
        "ON public.sms_outbox (related_prediction_id, subscriber_id) "
        "WHERE related_prediction_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_sms_outbox_prediction_subscriber")
    op.execute("DROP INDEX IF EXISTS public.uq_sms_outbox_alert_subscriber")
