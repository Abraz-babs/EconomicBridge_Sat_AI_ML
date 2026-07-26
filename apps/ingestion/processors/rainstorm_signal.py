"""Exceptional-rainfall detection from IMERG daily totals.

READ THIS BEFORE CHANGING A THRESHOLD — it is the record of a validation that
already failed once.

What this is NOT
----------------
This is **not a rainstorm detector**, despite the module's original name and
intent. It was built to catch the wind-damage storms in our register and
measured against them on real IMERG data (245 days per LGA, 2025+2026 wet
seasons, fetched 2026-07-26). It does not catch them, and no threshold can:

    LGA       event                         day    rank in its OWN LGA
    Riyom     2026-06-02, 100+ houses      9.5 mm  p72   (an ordinary day)
    Bassa     2026-07-20, 20+ houses       1.9 mm  p25   (below median)
    Shendam   2025-08-17, 50+ houses       0.5 mm  p45   (essentially dry)
    Mokwa     2025-05-29, 151 deaths      26.1 mm  p93   (wet, not exceptional)

Three of the four are convective **wind** damage — a downburst takes roofs off
under 20 mm of rain, and IMERG averages a 5 km cell into an 11 km box over 24 h
anyway. The fourth, Mokwa, was an **infrastructure failure**: an old railway
embankment released accumulated upstream water. Its rainfall was unremarkable
*for Mokwa*.

Catching Mokwa requires dropping to the p90 wet-day mark, which flags ~6% of all
LGA-days — roughly 4,100 alerts a season across 447 LGAs. That is not warning,
it is noise. So we do not do that, and we do not claim to detect these events.

What this IS
------------
A **flood-risk advisory**: this day's rainfall is exceptional *for this place*.
At the p99 wet-day mark that is ~1.2 days per LGA per season — about 340 alerts
nationally, ~2 a day. Rare enough to be worth reading, and genuinely useful for
pre-positioning ahead of a flood, which is a volume-driven hazard IMERG can
actually see.

Why per-LGA percentile, not a fixed mm threshold
------------------------------------------------
The original 50 mm/100 mm gate came from WMO/NiMet heavy-rain *advisory*
practice. It is above the observed 245-day maximum for Riyom (46 mm), so it
could never have fired there. Rainfall climatology varies far too much across
the Sahel-to-Middle-Belt gradient for one number: the same 25 mm is a p95 day in
Mokwa and a p90 day in Bassa. Each LGA is therefore judged against its own
wet-day distribution.

Dry days are excluded from that distribution. Including them drags the mean
toward zero (Mokwa is dry 54% of days) and makes every ordinary shower look
exceptional.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# Percentile of an LGA's own WET days that a reading must reach.
# Calibrated 2026-07-26 on real IMERG: p99 -> ~1.2 days/LGA/245d -> ~340 alerts
# nationally per season. p95 would be ~2,000 and p90 ~4,100. Do not lower this
# to chase a specific past event; see the module docstring.
ANOMALY_PERCENTILE = 99

# Absolute floor. Guards the arid case: in a very dry LGA the p99 wet day can
# itself be small, and 8 mm is not a flood risk anywhere.
MIN_ABSOLUTE_MM = 20.0

# A "wet day" — below this is drizzle and must not shape the baseline.
WET_DAY_MM = 1.0
# Wet days needed before a percentile means anything.
MIN_WET_DAYS = 20


@dataclass(frozen=True)
class RainstormSignal:
    """A day whose rainfall is exceptional for its own LGA."""

    rain_mm: float
    baseline_mm: float          # the LGA's median wet day
    threshold_mm: float         # its p99 wet day
    percentile: float           # where this day sits in its own distribution
    severity: str               # medium | high | critical
    confidence: float
    confidence_band: str

    def as_metrics(self) -> dict[str, float | str]:
        return {
            "rain_mm_day": self.rain_mm,
            "lga_median_wet_day_mm": self.baseline_mm,
            "lga_p99_wet_day_mm": self.threshold_mm,
            "percentile_in_lga": self.percentile,
            "instrument": "GPM IMERG Late Daily v07 (0.1deg, ~11km)",
            "interpretation": (
                "Rainfall exceptional for this LGA — a flood-risk advisory, "
                "not a damage assessment and NOT a rainstorm detection. "
                "Validated 2026-07-26: wind-damage storms are invisible in "
                "daily rainfall totals."
            ),
        }


def _severity_for(rain_mm: float, threshold_mm: float) -> tuple[str, float, str]:
    """Severity scales with how far past the LGA's own p99 the day sits."""
    over = rain_mm / threshold_mm if threshold_mm > 0 else 1.0
    if over >= 1.6:
        return "critical", 0.85, "HIGH"
    if over >= 1.25:
        return "high", 0.75, "MEDIUM"
    return "medium", 0.65, "MEDIUM"


def compute_rainstorm(
    daily_mm: list[float],
    *,
    recent_n: int = 1,
) -> RainstormSignal | None:
    """Flag the latest day if its rainfall is exceptional for this LGA.

    Args:
        daily_mm: consecutive daily totals, oldest first. The last `recent_n`
            are candidates; everything before is the baseline distribution.
        recent_n: how many trailing days count as "now".

    Returns:
        RainstormSignal for the wettest qualifying day, else None.
    """
    if len(daily_mm) <= recent_n:
        return None

    baseline_days = daily_mm[:-recent_n]
    peak = max(daily_mm[-recent_n:])

    wet = sorted(v for v in baseline_days if v >= WET_DAY_MM)
    if len(wet) < MIN_WET_DAYS:
        return None                      # too little history to call it unusual

    threshold = statistics.quantiles(wet, n=100)[ANOMALY_PERCENTILE - 1]
    if peak < threshold or peak < MIN_ABSOLUTE_MM:
        return None

    percentile = 100.0 * sum(1 for v in wet if v <= peak) / len(wet)
    severity, confidence, band = _severity_for(peak, threshold)
    return RainstormSignal(
        rain_mm=round(peak, 2),
        baseline_mm=round(statistics.median(wet), 2),
        threshold_mm=round(threshold, 2),
        percentile=round(percentile, 1),
        severity=severity,
        confidence=confidence,
        confidence_band=band,
    )
