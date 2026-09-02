"""Storm grouping and rolling accumulation.

The headline test replays the real Abuja storm of 2026-08-30/31 — the event the
platform missed — from the half-hourly rates IMERG actually published. If the
grouping ever regresses to calendar-day thinking, that test fails.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from processors.storm_event import (
    MAX_GAP,
    RAINING_MM_HR,
    find_storms,
    largest,
)


def _t(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 8, day, hh, mm, tzinfo=timezone.utc)


# The rates IMERG published over the FCT box, 30 Aug 2026 (UTC).
# 23:30 UTC is 00:30 WAT on the 31st — the peak fell on the NEXT calendar day.
ABUJA = [
    (_t(30, 20, 0), 1.7),
    (_t(30, 20, 30), 4.0),
    (_t(30, 21, 0), 4.0),
    (_t(30, 21, 30), 6.3),
    (_t(30, 22, 0), 5.5),
    (_t(30, 22, 30), 6.7),
    (_t(30, 23, 0), 4.1),
    (_t(30, 23, 30), 7.4),
    (_t(31, 0, 0), 0.2),
]


def test_abuja_storm_is_one_event_not_two_days() -> None:
    """The defect that caused the miss: a storm split by 00:00 UTC.

    The daily product reported 6.5 mm on the 30th and 0.1 mm on the 31st for
    Municipal Area Council, against a 30.6 mm gate. Grouped as a storm it is a
    single continuous event whose peak lands after midnight UTC.
    """
    events = find_storms(ABUJA)
    assert len(events) == 1, "one storm, not one per calendar day"
    e = events[0]
    assert e.start == _t(30, 20, 0)
    assert e.peak_mm_hr == 7.4
    assert e.peak_at == _t(30, 23, 30)
    assert e.crosses_midnight_utc, (
        "this is the property that explains the miss — it must be reported"
    )


def test_abuja_total_exceeds_either_calendar_day() -> None:
    """Grouping recovers rainfall that day-splitting threw away."""
    e = largest(ABUJA)
    assert e is not None
    # Sum of rates / 2 across the event.
    assert 19.0 <= e.total_mm <= 21.0, e.total_mm
    # And the 3-hour window carries most of it — the flash-flood horizon.
    assert e.accum[3] >= 12.0, e.accum


def test_rolling_window_is_not_clock_aligned() -> None:
    """A window must be able to start anywhere, or midnight bites again."""
    # 10 mm/hr for exactly one hour, straddling the top of an hour.
    series = [
        (_t(30, 12, 30), 10.0),
        (_t(30, 13, 0), 10.0),
    ]
    e = largest(series)
    assert e is not None
    assert e.accum[1] == 10.0, "1h window over two 30-min slices at 10 mm/hr"


def test_separate_storms_are_not_welded_together() -> None:
    """A long dry gap means two storms, not one twelve-hour monster."""
    series = [
        (_t(30, 2, 0), 5.0),
        (_t(30, 2, 30), 4.0),
        # ... quiet all day ...
        (_t(30, 18, 0), 6.0),
        (_t(30, 18, 30), 5.0),
    ]
    assert len(find_storms(series)) == 2


def test_brief_lull_stays_one_storm() -> None:
    """Convection is not perfectly continuous; a short pause is still one storm."""
    series = [
        (_t(30, 20, 0), 5.0),
        (_t(30, 20, 30), 0.0),   # lull, under RAINING_MM_HR
        (_t(30, 21, 0), 6.0),
    ]
    assert len(find_storms(series)) == 1


def test_drizzle_alone_is_not_a_storm() -> None:
    series = [(_t(30, h, 0), RAINING_MM_HR - 0.1) for h in range(6, 18)]
    assert find_storms(series) == []


def test_no_rain_returns_nothing_rather_than_a_zero_event() -> None:
    assert find_storms([]) == []
    assert largest([]) is None


def test_out_of_order_input_cannot_corrupt_grouping() -> None:
    """Callers fetch slices concurrently; order must not be load-bearing."""
    shuffled = list(reversed(ABUJA))
    assert len(find_storms(shuffled)) == 1
    assert find_storms(shuffled)[0].start == _t(30, 20, 0)


def test_gap_boundary_is_the_documented_one() -> None:
    """Exactly MAX_GAP joins; one slice more splits."""
    a = [(_t(30, 10, 0), 5.0), (_t(30, 10, 0) + MAX_GAP, 5.0)]
    b = [(_t(30, 10, 0), 5.0), (_t(30, 10, 0) + MAX_GAP + timedelta(minutes=30), 5.0)]
    assert len(find_storms(a)) == 1
    assert len(find_storms(b)) == 2


def test_duration_reflects_the_whole_storm() -> None:
    e = largest(ABUJA)
    assert e is not None
    # 20:00 through 23:30 + the last slice = 4 hours.
    assert e.duration_h == 4.0
