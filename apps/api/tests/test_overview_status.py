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
