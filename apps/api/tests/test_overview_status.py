"""Honest status chips for Overview shock rows (routers.overview.shock_status).

DB-free unit tests: a month-old seed drought must read HISTORICAL, never
ACTIVE — the 2026-07-14 rainy-season credibility bug.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from routers.overview import shock_status

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def test_seed_rows_are_historical_regardless_of_severity_and_age():
    assert shock_status("critical", "seed_v1", NOW, NOW) == (
        "HISTORICAL", "s-historical",
    )


def test_aged_out_live_rows_become_historical():
    old = NOW - timedelta(days=30)
    assert shock_status("critical", "shockguard_scan_v1", old, NOW) == (
        "HISTORICAL", "s-historical",
    )


def test_fresh_detector_rows_keep_live_severity_chip():
    fresh = NOW - timedelta(days=2)
    assert shock_status("critical", "shockguard_scan_v1", fresh, NOW) == (
        "ACTIVE", "s-active",
    )
    assert shock_status("medium", "shockguard_scan_v1", fresh, NOW) == (
        "MONITOR", "s-monitor",
    )


def test_missing_created_at_is_treated_as_historical():
    assert shock_status("high", "shockguard_scan_v1", None, NOW) == (
        "HISTORICAL", "s-historical",
    )


def test_unknown_severity_defaults_to_monitor_when_fresh():
    fresh = NOW - timedelta(days=1)
    assert shock_status("weird", "shockguard_scan_v1", fresh, NOW) == (
        "MONITOR", "s-monitor",
    )


# ─── Overview crop-health index reads the SATELLITE layer ─────────────────
# Regression for a fabricated public claim found 2026-07-28. The widget read
# `crop_predictions` — the leaf-photo diagnosis table — which held 59 rows
# across ten tenants, 50 of them seeded. It took the top two crops per tenant
# and rendered "Maize — Kebbi 0% healthy" as a red bar on the PUBLIC Overview,
# computed from two fabricated rows. That is a food-security claim about a real
# state, made from data we invented.


def test_index_reads_crop_health_not_crop_predictions():
    import inspect

    from routers import overview

    src = inspect.getsource(overview.crop_health)
    assert "FROM crop_health" in src
    assert "crop_predictions" not in src.split('"""')[-1], (
        "the photo-diagnosis table must not feed the statewide index"
    )


def test_unmeasured_lgas_are_excluded_not_counted_unhealthy():
    """An LGA with no NDVI has not been measured. Counting it in the
    denominator would turn our own coverage gap into someone's crop failure."""
    import inspect

    from routers import overview

    src = inspect.getsource(overview.crop_health)
    assert "ndvi IS NOT NULL" in src


def test_a_region_below_the_sample_floor_is_omitted_entirely():
    """0% from one reading is arithmetic, not a finding — and it renders
    identically to a real collapse."""
    import inspect

    from routers import overview

    assert overview._MIN_LGA_READINGS >= 3
    src = inspect.getsource(overview.crop_health)
    assert ">= _MIN_LGA_READINGS" in src


def test_rows_declare_their_sample_size():
    """A percentage with no denominator invites the reader to assume a big one."""
    import inspect

    from routers import overview

    src = inspect.getsource(overview.crop_health)
    assert "LGAs measured" in src
