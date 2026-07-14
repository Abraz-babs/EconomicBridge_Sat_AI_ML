"""create public.lga_signal_history (Tier-A prep for seasonal baselines)

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-14

Monthly per-LGA satellite aggregates (Sentinel-2 NDVI + Sentinel-1 VV dB)
backfilled from the CDSE Statistical API for 2023 onward. This is PURE
PREPARATION for the Sep–Oct 2026 detector-quality sprint: the seasonal
baselines (comparing this July against past Julys instead of against
all-history) need multi-year history that our live sweeps, which started in
2026, cannot provide.

NOTHING reads this table yet — detectors, feeds and dashboards are unchanged
until the seasonal-baseline work lands (deliberate Tier-A discipline: the
data is banked now, in a quiet window, so the later change is a pure logic
flip with the history already in place).

Populated by: apps/ingestion/scripts/backfill_lga_history.py (idempotent
upserts; safe to re-run / resume).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0035"
down_revision: Union[str, Sequence[str], None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.lga_signal_history (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id     VARCHAR(50) NOT NULL,
            lga           VARCHAR(120) NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            lat           DOUBLE PRECISION NOT NULL,
            signal        VARCHAR(20) NOT NULL,
            period_start  DATE NOT NULL,
            mean          DOUBLE PRECISION,
            std_dev       DOUBLE PRECISION,
            sample_count  INTEGER NOT NULL DEFAULT 0,
            fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_lga_hist_signal
                CHECK (signal IN ('ndvi', 'sar_vv_db')),
            CONSTRAINT uq_lga_hist
                UNIQUE (tenant_id, lga, signal, period_start)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lga_hist_lookup
            ON public.lga_signal_history (tenant_id, lga, signal)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.lga_signal_history")
