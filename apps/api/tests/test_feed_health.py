"""Unit tests for the feed-health watchdog.

The incident this exists for: the encroachment sweep ran daily for ~16 days,
recorded `succeeded` every time, and deleted 306 of 447 real crop_health NDVI
readings while doing it. So the load-bearing test here is not "does it notice a
dead feed" — it is "does it notice a LIVE feed that is eating our data", because
that is the one a status check cannot see.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.feed_health import (
    FEED_MAX_AGE_HOURS,
    STOCK_DROP_TOLERANCE,
    STOCK_PROBES,
    Finding,
    HealthReport,
    format_email,
)

NOW = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)


def _report(findings: list[Finding] | None = None) -> HealthReport:
    return HealthReport(checked_at=NOW, findings=findings or [],
                        observations=["a: 1", "b: 2"])


# ─── the regression check is the point ────────────────────────────────────


def test_the_july_incident_shape_is_a_finding() -> None:
    """447 real readings falling to 141 is a 68% drop. Whatever the tolerance,
    that must trip — it is the exact shape of the incident."""
    before, after = 447, 141
    assert after < before * (1 - STOCK_DROP_TOLERANCE)


def test_a_small_dip_is_tolerated() -> None:
    """LGAs legitimately clear a watch and months roll out of windows. A
    watchdog that cries at every wobble gets muted, and a muted watchdog is
    the same as none."""
    before = 447
    assert not (440 < before * (1 - STOCK_DROP_TOLERANCE))


def test_crop_health_probe_counts_only_real_readings() -> None:
    """The incident refilled rows with NULL ndvi. A plain COUNT(*) would have
    stayed at 447 and seen nothing wrong — the predicate is the whole trick."""
    probe = next(p for p in STOCK_PROBES if p.key == "crop_health_real_ndvi")
    assert probe.table == "crop_health"
    assert "ndvi IS NOT NULL" in probe.real_predicate


def test_shock_probe_excludes_the_cited_historical_register() -> None:
    """historical_v1 rows are hand-curated and static, so counting them would
    mask a live detector going quiet."""
    probe = next(p for p in STOCK_PROBES if p.key == "shock_events_live")
    assert "historical" not in probe.real_predicate
    assert "shockguard_scan_v1" in probe.real_predicate


def test_price_probe_excludes_seeds() -> None:
    probe = next(p for p in STOCK_PROBES if p.key == "crop_prices_real")
    assert "seed_v1" in probe.real_predicate


# ─── staleness ────────────────────────────────────────────────────────────


def test_every_daily_feed_has_a_staleness_budget() -> None:
    for source in ("encroachment_detector_v1", "shockguard_scan_v1",
                   "rainstorm_scan_v1"):
        assert source in FEED_MAX_AGE_HOURS
        # generous enough that one missed run is not an alarm...
        assert FEED_MAX_AGE_HOURS[source] >= 48
        # ...but tight enough that a fortnight of silence never passes.
        assert FEED_MAX_AGE_HOURS[source] <= 24 * 7


def test_monthly_feed_is_not_judged_on_a_daily_budget() -> None:
    assert FEED_MAX_AGE_HOURS["food_prices_v1"] > 24 * 31


# ─── reporting ────────────────────────────────────────────────────────────


def test_healthy_report_is_healthy_and_says_what_it_measured() -> None:
    r = _report()
    assert r.healthy
    assert "all feeds healthy" in r.summary()


def test_findings_make_the_report_unhealthy() -> None:
    r = _report([Finding("critical", "crop_health", "447 -> 141")])
    assert not r.healthy
    assert "critical" in r.summary()


def test_email_carries_the_findings_and_the_evidence() -> None:
    r = _report([Finding("critical", "kebbi/crop_health_real_ndvi",
                         "real rows fell 447 -> 141")])
    subject, body = format_email(r)
    assert "critical" in subject
    assert "447 -> 141" in body
    # observations are included so a reader can see what was checked and
    # passed — a report of only failures invites "is it even looking?"
    assert "a: 1" in body


def test_email_explains_why_the_watchdog_exists() -> None:
    """Whoever reads this at 3am may not know the history."""
    _, body = format_email(_report([Finding("warning", "x", "y")]))
    assert "sixteen days" in body
