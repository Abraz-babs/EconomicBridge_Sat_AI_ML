"""Extreme-rainfall detection from IMERG daily totals.

The flood detector keys off a *drop* in SAR backscatter. Rainfall is the mirror
image — we want the **upper tail**, a day that stands far above what this LGA
normally gets at this point in the season. Reusing the flood z-score with a
flipped sign would be wrong for two reasons:

  * Daily rainfall is not normally distributed. It is zero-inflated and heavily
    right-skewed — most days are 0 mm, so the standard deviation is dominated by
    dry days and a plain z-score fires on any ordinary wet day.
  * A relative anomaly alone is meaningless in an arid month: 6 mm against a
    baseline of 0.2 mm is a huge z-score and nobody's roof comes off.

So a day is flagged only when BOTH hold:

  1. **Absolute** — it cleared a real-world damaging-rain threshold. NiMet and
     WMO treat ~50 mm/day as heavy and ~100 mm/day as extreme for this region.
  2. **Relative** — it stands above this LGA's own wet-day baseline, so a
     genuinely wet climate isn't permanently alarmed. The baseline uses WET days
     only (dry days would drag the mean toward zero and make every storm look
     exceptional).

That pairing is what keeps the alert honest in both the Sahel and the Middle
Belt without per-tenant tuning.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# Damaging-rain thresholds, mm/day.
HEAVY_MM = 50.0
EXTREME_MM = 100.0
# A day must also be this many times the LGA's wet-day baseline.
MIN_RATIO = 2.0
# Baseline needs at least this many wet days to mean anything.
MIN_WET_DAYS = 5
# Below this, a "wet day" is drizzle and shouldn't shape the baseline.
WET_DAY_MM = 1.0


@dataclass(frozen=True)
class RainstormSignal:
    """A flagged extreme-rainfall day, with the evidence behind it."""

    rain_mm: float
    baseline_mm: float
    ratio: float
    severity: str            # medium | high | critical
    confidence: float        # 0..1
    confidence_band: str     # HIGH | MEDIUM | LOW

    def as_metrics(self) -> dict[str, float | str]:
        return {
            "rain_mm_day": self.rain_mm,
            "wet_day_baseline_mm": self.baseline_mm,
            "ratio_to_baseline": self.ratio,
            "heavy_threshold_mm": HEAVY_MM,
            "extreme_threshold_mm": EXTREME_MM,
            "instrument": "GPM IMERG Late Daily v07 (0.1deg)",
            "interpretation": (
                "LGA-level extreme-rainfall hazard, not a damage assessment — "
                "IMERG's ~11 km cell cannot resolve a single settlement."
            ),
        }


def _severity_for(rain_mm: float) -> tuple[str, float, str]:
    """Severity/confidence from the absolute total.

    Confidence reflects how far past the damaging threshold the day sits, not
    how certain we are that damage occurred — we never observe the damage.
    """
    if rain_mm >= EXTREME_MM * 1.5:
        return "critical", 0.92, "HIGH"
    if rain_mm >= EXTREME_MM:
        return "critical", 0.85, "HIGH"
    if rain_mm >= HEAVY_MM * 1.4:
        return "high", 0.78, "MEDIUM"
    return "medium", 0.68, "MEDIUM"


def compute_rainstorm(
    daily_mm: list[float],
    *,
    recent_n: int = 1,
) -> RainstormSignal | None:
    """Flag the most recent day(s) if they are a genuine extreme-rain event.

    Args:
        daily_mm: consecutive daily totals, oldest first. The last `recent_n`
            are the candidate day(s); everything before them is the baseline.
        recent_n: how many trailing days to consider as "now".

    Returns:
        RainstormSignal for the wettest qualifying recent day, else None.
    """
    if len(daily_mm) <= recent_n:
        return None

    baseline_days = daily_mm[:-recent_n]
    recent = daily_mm[-recent_n:]
    peak = max(recent)

    # Gate 1 — absolute. No amount of relative anomaly substitutes for rain
    # that was never heavy enough to damage anything.
    if peak < HEAVY_MM:
        return None

    wet = [v for v in baseline_days if v >= WET_DAY_MM]
    if len(wet) < MIN_WET_DAYS:
        # Not enough wet history to judge "unusual". Fall back to absolute-only,
        # but require the EXTREME bar so a thin archive can't cry wolf.
        if peak < EXTREME_MM:
            return None
        baseline = statistics.fmean(wet) if wet else 0.0
        ratio = round(peak / baseline, 2) if baseline > 0 else float("inf")
        severity, confidence, band = _severity_for(peak)
        return RainstormSignal(
            rain_mm=round(peak, 2),
            baseline_mm=round(baseline, 2),
            ratio=ratio if ratio != float("inf") else 0.0,
            severity=severity,
            # Thin baseline → we are less sure this is out of the ordinary.
            confidence=round(confidence - 0.10, 2),
            confidence_band="MEDIUM" if band == "HIGH" else "LOW",
        )

    baseline = statistics.fmean(wet)
    ratio = peak / baseline if baseline > 0 else float("inf")

    # Gate 2 — relative. A wet climate should not be permanently alarmed.
    if ratio < MIN_RATIO:
        return None

    severity, confidence, band = _severity_for(peak)
    return RainstormSignal(
        rain_mm=round(peak, 2),
        baseline_mm=round(baseline, 2),
        ratio=round(min(ratio, 999.0), 2),
        severity=severity,
        confidence=confidence,
        confidence_band=band,
    )
