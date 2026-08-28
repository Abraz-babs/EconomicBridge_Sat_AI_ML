"""Keep a permanent record of every encroachment watch ever raised.

`tasks/encroachment_detector.py` refreshes an LGA's watch on each successful
read: `DELETE FROM alert_events WHERE model_name = ... AND lga = ...`, then
re-insert if the signal still clears the threshold. That is correct for the
live panel — Farmland should show what is under watch NOW, not an accumulating
pile — but it means a watch ceases to exist the moment the LGA reads calm.

Nothing anywhere then remembers it happened. On 2026-08-28 the operator asked
why Farmland alerts appeared to repeat; the answer was that an LGA waits up to
REVISIT_DAYS (12) for its next look, and rainy-season cloud plus the six-day
CDSE credential outage stretched that further. But the question exposed a
larger gap: had those watches cleared instead, there would be no way to show
they were ever raised.

That absence bites in the same three places it did for rainfall (migration
0042):
  * an insurer's entire interest is verification, and "we watched Gwandu on
    25 Aug" with nothing behind it is not evidence;
  * a quiet week makes the module look inert, with no way to show the work;
  * the operator's stated requirement is to "not miss anything" — a live table
    that deletes by design cannot satisfy that on its own.

APPEND-ONLY and separate from `alert_events` on purpose: the live read path is
untouched, the panel keeps behaving exactly as it does now, and nothing in
production changes shape. This table only ever gains rows.

UNIQUE (lga, observed_date): a re-run or a manual sweep on the same day must
not double-count the same observation in what is meant to be evidence.

Revision ID: 0045
Revises: 0044
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0045"
down_revision: Union[str, Sequence[str], None] = "0044"
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
            CREATE TABLE IF NOT EXISTS "{schema}".encroachment_watch_history (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id       VARCHAR(50)  NOT NULL,
                lga             VARCHAR(120) NOT NULL,
                lon             DOUBLE PRECISION,
                lat             DOUBLE PRECISION,

                -- What was watched, and how strongly.
                severity        VARCHAR(20)  NOT NULL,
                score           DOUBLE PRECISION NOT NULL
                    CHECK (score BETWEEN 0 AND 1),
                zone_name       TEXT,

                -- The reading behind it. `components` carries the per-signal
                -- breakdown (NDVI z, SAR z, fire count, night-light) so a
                -- reviewer can see WHY without re-running the detector.
                components      JSONB NOT NULL DEFAULT '{{}}'::jsonb,

                -- Model-derived impact estimates, kept because the alert card
                -- showed them and a later reader will ask what we told people.
                affected_area_ha    INTEGER,
                livelihoods_at_risk INTEGER,

                observed_date   DATE         NOT NULL,
                detector_version VARCHAR(50) NOT NULL,
                raised_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_encroach_hist_raised '
            f'ON "{schema}".encroachment_watch_history (raised_at DESC)'
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_encroach_hist_lga '
            f'ON "{schema}".encroachment_watch_history (lga, raised_at DESC)'
        )
        # One watch per LGA per observed day — see the docstring.
        op.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_encroach_hist_lga_day '
            f'ON "{schema}".encroachment_watch_history (lga, observed_date)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(
            f'DROP TABLE IF EXISTS "tenant_{tenant}".encroachment_watch_history'
        )
