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


def test_no_stock_probe_watches_a_self_replacing_feed() -> None:
    """The watchdog's FIRST live alert, 2026-07-29, was wrong:

        [CRITICAL] senegal/shock_events_live  real rows fell 2 -> 0

    Senegal's rows were gone because that run of the rainfall scan succeeded
    and correctly found no exceptional rainfall there, while kaduna gained 3
    and plateau 5 in the same sweep. Both live detectors call _replace_prior
    every run, so their row count tracks current weather, not accumulated
    knowledge — it is MEANT to fall, and zero is a normal answer.

    Stock probes assume a floor that only rises. Pointing one at a
    self-replacing table guarantees a false alarm on the first quiet day, and
    an alert people learn to ignore is worse than no alert at all."""
    tables = {p.table for p in STOCK_PROBES}
    assert "shock_events" not in tables, (
        "shock_events is replaced every run; its health is the staleness check"
    )


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


# ─── the watchdog's own first mistake, made permanent as a test ───────────
# On its first production run FEED_MAX_AGE_HOURS said `firms_ingest_v1` and the
# report opened with "has NEVER recorded a successful run" — about a feed on
# 450 runs, 448 successful. The task writes `MODIS_NRT`. A budget keyed on a
# string nobody writes watches nothing, silently, for as long as the typo lives.


def test_firms_budget_uses_the_string_the_task_actually_writes() -> None:
    assert "MODIS_NRT" in FEED_MAX_AGE_HOURS
    assert "firms_ingest_v1" not in FEED_MAX_AGE_HOURS


def test_an_unwatched_source_is_itself_a_finding() -> None:
    """The inverse blind spot. A feed writing runs with no budget must announce
    itself, so the next rename cannot quietly go unmonitored."""
    from services.feed_health import _check_unmonitored

    r = _report()
    _check_unmonitored(r, {"encroachment_detector_v1", "some_new_feed_v9"})
    assert [f.subject for f in r.findings] == ["some_new_feed_v9"]
    assert r.findings[0].severity == "warning"      # a gap, not a breakage


def test_known_sources_do_not_trigger_the_unwatched_check() -> None:
    from services.feed_health import _check_unmonitored

    r = _report()
    _check_unmonitored(r, set(FEED_MAX_AGE_HOURS))
    assert r.findings == []


def test_shared_tables_are_probed_once_not_once_per_tenant() -> None:
    """crop_prices lives in public. Probing it per tenant printed the same 456
    ten times — ten identical lines read as ten checks and are one, and they
    bury the findings that matter."""
    probe = next(p for p in STOCK_PROBES if p.key == "crop_prices_real")
    assert probe.scope == "global"
    per_tenant = [p.key for p in STOCK_PROBES if p.scope == "tenant"]
    assert "crop_health_real_ndvi" in per_tenant     # genuinely per-tenant
