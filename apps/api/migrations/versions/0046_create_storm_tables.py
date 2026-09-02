"""Storm events and the intensity record they are judged against.

Two tables per tenant, for every pilot — this is one engine across all 447
LGAs, not a fix bolted onto the territory that exposed the problem.

WHY
---
Abuja flooded on 2026-08-30/31 and the platform reported nothing. The daily
rainfall product accumulates over a calendar day in UTC; West African
convection runs late afternoon into the night, so one storm (21:00-00:30 WAT)
was split across two granules and neither half looked like anything. The same
event also showed a 3x3 MEAN at an LGA centroid reading 6.5 mm while the
surrounding box held ~22 mm.

`processors/storm_event.py` now reconstructs storms from half-hourly rate.
These tables give it somewhere to record what it finds, and something to judge
it against.

storm_intensity_daily
  One row per LGA per day: the day's worst 1h and 3h rolling accumulation and
  peak rate. This is the SAMPLE from which per-LGA percentiles are computed —
  the same discipline as the daily p99 in processors/rainstorm_signal.py, and
  for the same reason: IMERG's absolute values are biased low over convection,
  but its relative variation for a given place is informative. "The most
  intense hour Bwari has seen in 90 days" is defensible where "7 mm/hr" alone
  is not.

  It grows by itself. The daily scan appends one row per LGA, so the baseline
  improves every day without a separate maintenance job, and a bootstrap only
  has to cover enough history to be usable rather than all of it.

storm_events
  Detections worth keeping: the storm, its timing, and what it delivered.
  Append-only and separate from shock_events so the live ShockGuard feed and
  its read path are untouched.

UNIQUE keys on both: a re-run or a manual sweep must not double-count one
observation in what is meant to be evidence — the same rule as
rainfall_advisory_history (0042) and encroachment_watch_history (0045).

Revision ID: 0046
Revises: 0045
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0046"
down_revision: Union[str, Sequence[str], None] = "0045"
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
            CREATE TABLE IF NOT EXISTS "{schema}".storm_intensity_daily (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id     VARCHAR(50)  NOT NULL,
                lga           VARCHAR(120) NOT NULL,
                day           DATE         NOT NULL,

                -- The day's worst rolling accumulations, in mm. Rolling, not
                -- clock-aligned: alignment to calendar boundaries is the defect
                -- being fixed.
                max_1h_mm     DOUBLE PRECISION,
                max_3h_mm     DOUBLE PRECISION,
                max_6h_mm     DOUBLE PRECISION,
                -- Peak half-hourly rate, mm/hr.
                peak_mm_hr    DOUBLE PRECISION,

                -- How much of the day we actually saw. A percentile built from
                -- a partly-observed day is not comparable with a full one, so
                -- the sample carries its own coverage and the reader decides.
                slices_seen   INTEGER      NOT NULL DEFAULT 0,
                slices_expected INTEGER    NOT NULL DEFAULT 48,

                created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_storm_intensity_lga_day
                    UNIQUE (lga, day)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_storm_intensity_lookup '
            f'ON "{schema}".storm_intensity_daily (lga, day DESC)'
        )

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".storm_events (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id     VARCHAR(50)  NOT NULL,
                lga           VARCHAR(120) NOT NULL,
                lon           DOUBLE PRECISION,
                lat           DOUBLE PRECISION,

                -- The storm itself, in UTC. started_at is the key that makes a
                -- storm a storm rather than a date: it may sit on the previous
                -- calendar day from the peak.
                started_at    TIMESTAMPTZ  NOT NULL,
                ended_at      TIMESTAMPTZ  NOT NULL,
                peak_at       TIMESTAMPTZ  NOT NULL,
                crosses_midnight_utc BOOLEAN NOT NULL DEFAULT FALSE,

                peak_mm_hr    DOUBLE PRECISION NOT NULL,
                total_mm      DOUBLE PRECISION NOT NULL,
                max_1h_mm     DOUBLE PRECISION,
                max_3h_mm     DOUBLE PRECISION,
                max_6h_mm     DOUBLE PRECISION,
                duration_h    DOUBLE PRECISION,

                -- Where this sat in the LGA's own record, and how much record
                -- there was. A percentile over 9 days means little and must not
                -- be presentable as though it meant a lot.
                percentile_1h DOUBLE PRECISION,
                percentile_3h DOUBLE PRECISION,
                baseline_days INTEGER,

                severity      VARCHAR(20),
                detector_version VARCHAR(50) NOT NULL,
                detected_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_storm_events_lga_start
                    UNIQUE (lga, started_at)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_storm_events_recent '
            f'ON "{schema}".storm_events (detected_at DESC)'
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_storm_events_lga '
            f'ON "{schema}".storm_events (lga, started_at DESC)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP TABLE IF EXISTS "{schema}".storm_events')
        op.execute(f'DROP TABLE IF EXISTS "{schema}".storm_intensity_daily')
