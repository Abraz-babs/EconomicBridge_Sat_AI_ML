"""Storm events from half-hourly rainfall — intensity and true duration.

WHAT THIS FIXES
---------------
`processors/rainstorm_signal.py` judges a CALENDAR DAY's total against that
LGA's own p99 wet day. That is the right instrument for "was yesterday
exceptionally wet here", and it stays. It cannot, however, see a storm, because
a calendar day is not a storm:

  * West African convection runs late afternoon into the night, so a storm
    routinely crosses 00:00 UTC and is split across two daily granules, each
    half looking ordinary. Abuja, 2026-08-30: one continuous storm from 21:00
    to 00:30 WAT, reported as 6.5 mm then 0.1 mm against a 30.6 mm gate. The
    city flooded. Nothing could have fired.
  * Flooding is driven by INTENSITY over hours, not by a 24-hour sum. 30 mm in
    forty minutes floods a city; the same 30 mm over twelve hours does not.
    A daily total cannot distinguish them.

So this module works on rolling windows over half-hourly rate, which is how
operational flash-flood guidance is actually expressed.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not claim to detect or predict a flood. It reports what fell, how fast,
and over how long. Whether that floods a given place depends on drainage,
soil saturation, slope and how much of the ground is concrete — none of which
we observe. The Kebbi 2024 backtest scored 0 of 11 on a detector that confused
"a signal is present" with "a flood happened"; the lesson is in the naming
here. This produces a STORM event, not a flood alert.

HONEST LIMIT: IMERG averages over ~11 km cells and is known to underestimate
short, violent convection. Every figure here is a LOWER BOUND on what actually
fell. Never present one as a gauge reading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# A slice at or above this rate counts as "raining" for the purpose of joining
# slices into one storm. Below it, drizzle would weld separate storms together
# across a quiet night and report a twelve-hour "event" that never happened.
RAINING_MM_HR = 0.5

# A storm may pause briefly — a convective system passing overhead is not
# perfectly continuous. Two rain periods separated by no more than this are one
# storm; longer and they are two. 90 minutes is three empty slices.
MAX_GAP = timedelta(minutes=90)

# Rolling windows reported for every event. 1h and 3h are the flash-flood
# horizons; 6h and 24h carry the riverine and saturation story.
WINDOWS_H: tuple[int, ...] = (1, 3, 6, 24)

# Half of an hour's rate is that half-hour's depth.
_SLICE_HOURS = 0.5


@dataclass(frozen=True, slots=True)
class StormEvent:
    """One continuous storm over one place."""

    start: datetime               # UTC, first raining slice
    end: datetime                 # UTC, end of the last raining slice
    peak_mm_hr: float             # highest half-hourly rate
    peak_at: datetime             # when that peak fell
    total_mm: float               # depth over the whole event
    accum: dict[int, float]       # hours -> max rolling depth (mm)
    slices: int                   # raining slices, for provenance

    @property
    def duration_h(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0

    @property
    def crosses_midnight_utc(self) -> bool:
        """True when a calendar-day total would have split this storm.

        This is the property that explains the Abuja miss, so it is reported
        rather than left for a reader to infer.
        """
        return self.start.date() != self.end.date()


def _rolling_max(
    series: list[tuple[datetime, float]], hours: int,
) -> float:
    """Greatest depth accumulating in any `hours` window across the series.

    Walks every possible window rather than aligning to clock boundaries —
    aligning is precisely the mistake the daily product makes.
    """
    if not series:
        return 0.0
    span = timedelta(hours=hours)
    best = 0.0
    for i, (t0, _) in enumerate(series):
        total = 0.0
        for t, rate in series[i:]:
            if t - t0 >= span:
                break
            total += rate * _SLICE_HOURS
        if total > best:
            best = total
    return best


def find_storms(series: list[tuple[datetime, float]]) -> list[StormEvent]:
    """Group a rate series into storms, newest last.

    `series` is (slice start UTC, mm/hr), any order; it is sorted here so a
    caller cannot silently corrupt the grouping by passing slices out of order.
    """
    pts = sorted((t, r) for t, r in series if r is not None)
    raining = [(t, r) for t, r in pts if r >= RAINING_MM_HR]
    if not raining:
        return []

    groups: list[list[tuple[datetime, float]]] = [[raining[0]]]
    for t, r in raining[1:]:
        if t - groups[-1][-1][0] <= MAX_GAP:
            groups[-1].append((t, r))
        else:
            groups.append([(t, r)])

    events: list[StormEvent] = []
    for g in groups:
        peak_at, peak = max(g, key=lambda x: x[1])
        start = g[0][0]
        end = g[-1][0] + timedelta(minutes=30)
        # Accumulations run over this event's OWN span including its lulls -
        # not over the raining slices alone, which would skip a lull and
        # overstate the rate, and not over the whole series, which would hand
        # every storm in the window the largest storm's numbers. That second
        # error is invisible while a window holds one storm and silently wrong
        # the moment it holds two.
        inside = [(t, r) for t, r in pts if start <= t < end]
        events.append(StormEvent(
            start=start,
            end=end,
            peak_mm_hr=round(peak, 2),
            peak_at=peak_at,
            total_mm=round(sum(r * _SLICE_HOURS for _, r in inside), 2),
            accum={h: round(_rolling_max(inside, h), 2) for h in WINDOWS_H},
            slices=len(g),
        ))
    return events


def window_maxima(
    series: list[tuple[datetime, float]],
) -> tuple[dict[int, float], float] | None:
    """Rolling maxima and peak rate over a whole series, ignoring storm bounds.

    This is what the intensity BASELINE is built from, and it is deliberately
    not "the largest storm's numbers". A day's worst hour is a property of the
    day: an afternoon squall can deliver less total rain than an all-night
    soaking while being far more intense, so picking the storm with the highest
    total and reporting its peak understates the day.

    Returns (accumulations by hour, peak mm/hr), or None if it never rained.
    """
    pts = sorted((t, r) for t, r in series if r is not None)
    if not any(r >= RAINING_MM_HR for _, r in pts):
        return None
    return (
        {h: round(_rolling_max(pts, h), 2) for h in WINDOWS_H},
        round(max(r for _, r in pts), 2),
    )


def largest(series: list[tuple[datetime, float]]) -> StormEvent | None:
    """The storm carrying the most rain, or None if it never rained."""
    events = find_storms(series)
    if not events:
        return None
    return max(events, key=lambda e: e.total_mm)
