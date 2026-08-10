"""Keep a permanent record of every rainfall advisory issued.

`tasks/rainstorm_scan.py` calls `_replace_prior()` before each scan, which does
`DELETE FROM shock_events WHERE source = 'rainstorm_scan_v1'`. That is right for
the dashboard — the panel should show what is advised NOW, not an accumulating
pile — but it means an advisory ceases to exist the moment it is superseded.

Observed 2026-08-10: an operator saw a Nasarawa advisory in the morning and
found it gone by afternoon. Nothing had failed; the 08:00 UTC scan replaced the
set and Nasarawa no longer cleared its threshold. But there was no way to show
that the advisory had ever been issued.

That absence bites in three places:
  * a quiet demo day makes the platform look inert, with yesterday's advisories
    unrecoverable;
  * an insurer's whole interest is verification, and "we advised Doma on 9 Aug"
    with nothing behind it is not evidence;
  * once SMS goes out to cooperatives, the message record must tie back to the
    advisory that caused it — otherwise the delivery log points at nothing.

This table is APPEND-ONLY and separate from `shock_events` on purpose: the live
read path is untouched, so the dashboard keeps behaving exactly as it does now
and nothing in production changes shape.

Revision ID: 0042
Revises: 0041
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0042"
down_revision: Union[str, Sequence[str], None] = "0041"
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
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".rainfall_advisory_history (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id       VARCHAR(50)  NOT NULL,
                lga             VARCHAR(120) NOT NULL,
                lon             DOUBLE PRECISION NOT NULL,
                lat             DOUBLE PRECISION NOT NULL,

                -- What was advised.
                severity        VARCHAR(20)  NOT NULL,
                confidence      DOUBLE PRECISION NOT NULL
                    CHECK (confidence BETWEEN 0 AND 1),
                confidence_band VARCHAR(10)  NOT NULL,

                -- The reading behind it. observed_date is the DAY IT RAINED;
                -- advised_at is when we said so. They differ by the IMERG
                -- latency and an operator asking "why did I get this today"
                -- needs both.
                observed_date   DATE         NOT NULL,
                rain_mm_day     DOUBLE PRECISION,
                lga_p99_wet_day_mm DOUBLE PRECISION,
                percentile_in_lga  DOUBLE PRECISION,

                metrics         JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
                detector_version VARCHAR(50) NOT NULL,
                advised_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_rain_hist_advised '
            f'ON "{schema}".rainfall_advisory_history (advised_at DESC)'
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_rain_hist_lga '
            f'ON "{schema}".rainfall_advisory_history (lga, advised_at DESC)'
        )
        # One advisory per LGA per observed day. A scan re-run (manual trigger,
        # task replacement mid-run) must not double-count the same rainfall in
        # what is meant to be an evidence record.
        op.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_rain_hist_lga_day '
            f'ON "{schema}".rainfall_advisory_history (lga, observed_date)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(
            f'DROP TABLE IF EXISTS "tenant_{tenant}".rainfall_advisory_history'
        )
