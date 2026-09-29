"""Nothing on the platform is invented (operator rule, 2026-09-29).

Pins the replacements: the status bar reads the feeds, the trend reads what
was stored, placeholder and synthetic-model alerts never surface, reports use
measured impact only, and rainfall readings are named as rainfall.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from repositories.alerts import _apply_filters
from routers.overview_live import FEED_LABELS, feed_states, month_series
from routers.reports import REPORT_SPECS
from services.data_source import REAL_ALERT
from services.feed_health import FEED_MAX_AGE_HOURS
from services.intelligence_feed import _row_to_feed_event

NOW = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)


def test_status_bar_lists_every_monitored_feed_by_its_real_last_run():
    rows = [
        {"source": "storm_scan_v1", "ok_at": NOW - timedelta(hours=10), "last_status": "succeeded"},
        {"source": "MODIS_NRT", "ok_at": NOW - timedelta(days=5), "last_status": "failed"},
    ]
    feeds = {f.source: f for f in feed_states(rows, NOW)}
    assert set(feeds) == set(FEED_MAX_AGE_HOURS)
    assert feeds["storm_scan_v1"].current
    assert not feeds["MODIS_NRT"].current            # past its 72 h budget
    assert feeds["wb_rtp_v1"].last_success_at is None and not feeds["wb_rtp_v1"].current


def test_every_monitored_feed_has_a_plain_label():
    assert set(FEED_MAX_AGE_HOURS) <= set(FEED_LABELS)


def test_the_retired_synthetic_conflict_feed_is_not_monitored():
    assert "conflict_pipeline_v1" not in FEED_MAX_AGE_HOURS


def test_trend_is_six_calendar_months_and_a_quiet_month_reads_zero():
    rows = [{"month": date(2026, 9, 1), "readings": 1200, "runs": 40},
            {"month": date(2026, 6, 1), "readings": 300, "runs": 12}]
    months = month_series(rows, date(2026, 9, 29))
    assert [m.month for m in months] == [date(2026, m, 1) for m in (4, 5, 6, 7, 8, 9)]
    assert [m.readings for m in months] == [0, 0, 300, 0, 0, 1200]


def test_trend_crosses_the_new_year():
    months = month_series([], date(2027, 2, 3))
    assert months[0].month == date(2026, 9, 1) and months[-1].month == date(2027, 2, 1)


def test_placeholder_and_synthetic_model_alerts_never_surface():
    assert "'seed'" in REAL_ALERT and "synthetic" in REAL_ALERT
    from sqlalchemy import select

    from models.alert_event import AlertEvent
    stmt = _apply_filters(select(AlertEvent), severity=None, status=None, alert_type=None,
                          lga=None, since=None, until=None, include_deleted=False)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "seed" in sql and "synthetic" in sql


def test_farmland_report_is_measured_only():
    spec = REPORT_SPECS["farmland"]
    labels = [m.label for m in spec.metrics]
    assert not any("value" in lbl.lower() or "livelihood" in lbl.lower() for lbl in labels)
    assert "seed" in (spec.real_only or "") and "synthetic" in (spec.real_only or "")


def _shock_row(source: str, event_type: str) -> dict:
    return {"kind": "shock_event", "subtype": event_type, "severity": "medium",
            "region": "Aleiro", "source": source, "observed_at": NOW}


def test_rainfall_readings_are_named_rainfall_not_radar_water():
    ev = _row_to_feed_event("kebbi", _shock_row("rainstorm_scan_v1", "flood"))
    assert ev.title.startswith("Extreme rainfall")
    ev = _row_to_feed_event("kebbi", _shock_row("storm_scan_v1", "rainstorm"))
    assert ev.title.startswith("Storm")
    ev = _row_to_feed_event("kebbi", _shock_row("shockguard_scan_v1", "flood"))
    assert "radar" in ev.title.lower()


def test_land_alerts_are_named_by_what_was_measured():
    from services.intelligence_feed import _alert_event_title
    assert _alert_event_title({"subtype": "conflict"}, "kebbi", "Soba").startswith("Land-disturbance alert")


def test_active_response_names_rows_by_instrument():
    from routers.overview import event_name
    assert event_name("flood", "rainstorm_scan_v1") == "Extreme rainfall"
    assert event_name("rainstorm", "storm_scan_v1") == "Storm"
    assert event_name("flood", "shockguard_scan_v1") == "Radar surface water"
    assert event_name("drought", "shockguard_scan_v1") == "Greenness below normal"
    assert event_name("flood", "historical_v1") == "Flood"      # a recorded disaster keeps its name
