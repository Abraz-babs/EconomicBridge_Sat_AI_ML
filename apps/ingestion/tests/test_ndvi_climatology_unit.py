"""Seasonal NDVI climatology — the drought detector's baseline.

Each test here pins a decision that was measured, not chosen. The numbers in
the assertions come from the walk over public.lga_signal_history documented in
processors/ndvi_climatology.py; if that measurement is redone and disagrees,
the constants and these tests move together.
"""
from __future__ import annotations

import pytest

from processors.ndvi_climatology import (
    MIN_ANOMALY,
    MIN_CLIMATOLOGY_YEARS,
    MIN_INTERANNUAL_STD,
    MIN_VALID_NDVI,
    build_climatology,
    seasonal_drought,
)


def _rows(values_by_year: dict[int, float], *, month: int = 11,
          tenant: str = "kebbi", lga: str = "Argungu"):
    return [(tenant, lga, y, month, v) for y, v in values_by_year.items()]


# ─── the seasonal question itself ─────────────────────────────────────────


def test_normal_dry_season_reading_does_not_fire() -> None:
    """The whole point: November NDVI of 0.22 is NORMAL for November.

    The old rolling-window detector saw 0.55 (Sep) -> 0.22 (Nov) as a 0.33 drop
    and called it critical drought. Judged against previous Novembers it is
    unremarkable.
    """
    clim = build_climatology(_rows({2023: 0.21, 2024: 0.23, 2025: 0.22}))
    assert seasonal_drought(0.22, clim, tenant="kebbi", lga="Argungu", month=11) is None


def test_genuinely_dry_november_does_fire() -> None:
    """Same month, but well below what this LGA normally does in November."""
    clim = build_climatology(_rows({2023: 0.40, 2024: 0.42, 2025: 0.41}))
    sig = seasonal_drought(0.28, clim, tenant="kebbi", lga="Argungu", month=11)
    assert sig is not None
    assert sig.anomaly < -MIN_ANOMALY
    assert sig.z < 0


# ─── the epsilon trap, in its new disguise ────────────────────────────────


def test_flat_history_cannot_manufacture_certainty() -> None:
    """Two near-identical years give a near-zero std. Dividing by it is the bug.

    This is the same defect that once produced z=-151 at "confidence 1.0" from
    a flat rolling baseline. Here the cell std is ~0.0005; without pooling and
    the floor, a 0.12 anomaly divides out to z=-240.
    """
    clim = build_climatology(_rows({2023: 0.4000, 2024: 0.4010}))
    sig = seasonal_drought(0.28, clim, tenant="kebbi", lga="Argungu", month=11)
    assert sig is not None
    assert sig.climatology_std >= MIN_INTERANNUAL_STD
    assert abs(sig.z) < 20, f"z={sig.z} — denominator collapsed again"


def test_spread_never_falls_below_measurement_uncertainty() -> None:
    clim = build_climatology(_rows({2023: 0.40, 2024: 0.40, 2025: 0.40}))
    assert clim.spread("kebbi", 11, 0.0) >= MIN_INTERANNUAL_STD


def test_a_volatile_lga_is_harder_to_alarm_about_not_easier() -> None:
    """Per-cell std is used only when LARGER than the pooled estimate."""
    steady = build_climatology(_rows({2023: 0.40, 2024: 0.41, 2025: 0.40}))
    volatile = build_climatology(_rows({2023: 0.25, 2024: 0.55, 2025: 0.40}))
    same_reading = 0.28
    s_steady = seasonal_drought(same_reading, steady, tenant="kebbi",
                                lga="Argungu", month=11)
    s_volatile = seasonal_drought(same_reading, volatile, tenant="kebbi",
                                  lga="Argungu", month=11)
    assert s_steady is not None
    # Same mean-ish, but the volatile place must not produce a HIGHER confidence.
    if s_volatile is not None:
        assert s_volatile.confidence <= s_steady.confidence


# ─── data quality ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [-0.46, -0.013, 0.0, 0.05, 0.099])
def test_non_vegetation_readings_are_not_drought(bad: float) -> None:
    """1% of banked readings are NEGATIVE — water or cloud, never vegetation.

    Treating them as drought is how "ndvi=0.047 vs normal 0.358, critical"
    happened in the first validation run.
    """
    clim = build_climatology(_rows({2023: 0.40, 2024: 0.42, 2025: 0.41}))
    assert seasonal_drought(bad, clim, tenant="kebbi", lga="Argungu", month=11) is None


def test_bad_readings_are_excluded_from_the_normal_too() -> None:
    """A cloud-hit year must not drag the baseline down and mask real drought."""
    clim = build_climatology(_rows({2023: 0.40, 2024: 0.42, 2025: -0.20, 2026: 0.41}))
    cell = clim.cell("kebbi", "Argungu", 11)
    assert cell is not None
    assert cell.years == 3, "the invalid year should not count toward coverage"
    assert cell.mean > 0.39


# ─── no baseline means no claim ───────────────────────────────────────────


def test_single_year_is_not_a_normal() -> None:
    clim = build_climatology(_rows({2025: 0.41}))
    cell = clim.cell("kebbi", "Argungu", 11)
    assert cell is not None and not cell.usable
    assert seasonal_drought(0.20, clim, tenant="kebbi", lga="Argungu", month=11) is None


def test_unknown_lga_returns_none_rather_than_guessing() -> None:
    clim = build_climatology(_rows({2023: 0.40, 2024: 0.42, 2025: 0.41}))
    assert seasonal_drought(0.10, clim, tenant="kebbi", lga="Nowhere", month=11) is None


def test_min_years_constant_matches_the_gate() -> None:
    assert MIN_CLIMATOLOGY_YEARS == 2
    clim = build_climatology(_rows({2024: 0.40, 2025: 0.42}))
    cell = clim.cell("kebbi", "Argungu", 11)
    assert cell is not None and cell.usable


# ─── leave-one-year-out, the property the validation relies on ────────────


def test_exclude_year_removes_that_year_from_the_normal() -> None:
    rows = _rows({2023: 0.40, 2024: 0.42, 2025: 0.05})
    with_all = build_climatology(rows)
    without = build_climatology(rows, exclude_year=2025)
    a = with_all.cell("kebbi", "Argungu", 11)
    b = without.cell("kebbi", "Argungu", 11)
    assert a is not None and b is not None
    # 0.05 is below MIN_VALID_NDVI so it never counted; excluding 2024 must.
    dropped = build_climatology(rows, exclude_year=2024)
    c = dropped.cell("kebbi", "Argungu", 11)
    assert c is not None and c.years == 1


def test_month_is_respected_not_ignored() -> None:
    """A November reading must not be judged against June's normal."""
    rows = (_rows({2023: 0.20, 2024: 0.22, 2025: 0.21}, month=11)
            + _rows({2023: 0.60, 2024: 0.62, 2025: 0.61}, month=6))
    clim = build_climatology(rows)
    # Normal for November; would look catastrophic against June.
    assert seasonal_drought(0.21, clim, tenant="kebbi", lga="Argungu", month=11) is None
    sig = seasonal_drought(0.21, clim, tenant="kebbi", lga="Argungu", month=6)
    assert sig is not None and sig.severity == "critical"


def test_valid_ndvi_floor_is_what_the_measurement_said() -> None:
    assert MIN_VALID_NDVI == 0.10
