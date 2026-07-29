"""create public.feed_health_marks (watchdog baselines)

The watchdog in services/feed_health.py answers two questions. "Did the feed
run?" needs no storage — public.ingestion_runs already holds it. "Is our stock
of real data going backwards?" does, because a fall is only visible against
what we held last time.

That second question is the one that matters. In July 2026 the encroachment
sweep ran daily for about sixteen days, reported `succeeded` every time, and
deleted 306 of 447 real crop_health NDVI readings while it did. No status check
could have seen it; a row count over time would have caught it on day one.

One row per (tenant, probe), overwritten each run — this is a high-water
reference, not a time series. If a trend is ever wanted, that is a separate
table rather than an unbounded growth of this one.

Revision ID: 0038
Revises: 0037
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0038"
down_revision: Union[str, Sequence[str], None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.feed_health_marks (
            tenant_id   VARCHAR(50)  NOT NULL,
            probe       VARCHAR(64)  NOT NULL,
            value       BIGINT       NOT NULL,
            recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_feed_health_marks PRIMARY KEY (tenant_id, probe)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.feed_health_marks")
