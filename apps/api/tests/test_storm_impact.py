"""The storm-impact merge: one row per LGA, heaviest rain first, real exposure."""
from datetime import datetime, timezone

from routers.shockguard import _merge_impact


def _t(h, m=0):
    return datetime(2026, 9, 19 if h >= 23 else 20, h, m, tzinfo=timezone.utc)


ADV = [
    {"lga": "Bunza", "rain_mm_day": 101.56, "severity": "medium", "sms_recipients": 11,
     "sms_dispatched_at": datetime(2026, 9, 22, 8, 11, tzinfo=timezone.utc)},
    {"lga": "Birnin Kebbi", "rain_mm_day": 84.5, "severity": "critical", "sms_recipients": None,
     "sms_dispatched_at": None},
]
STORMS = [
    {"lga": "Bunza", "lon": 4.02, "lat": 12.1, "started_at": _t(23, 30), "ended_at": _t(7),
     "peak_at": _t(0, 30), "total_mm": 82.53, "peak_mm_hr": 30.27, "percentile_3h": 96.3, "baseline_days": 27},
    {"lga": "Bunza", "lon": 4.02, "lat": 12.1, "started_at": _t(15), "ended_at": _t(16),
     "peak_at": _t(15, 30), "total_mm": 5.0, "peak_mm_hr": 4.0, "percentile_3h": 40.0, "baseline_days": 27},
    {"lga": "Arewa Dandi", "lon": 4.09, "lat": 12.77, "started_at": _t(23, 30), "ended_at": _t(7),
     "peak_at": _t(2), "total_mm": 88.33, "peak_mm_hr": 32.65, "percentile_3h": 96.6, "baseline_days": 29},
]
EXPOSURE = {
    "Bunza": {"villages": 480, "people": 193002, "under5": 38906, "dark": 436, "lon": 4.0, "lat": 12.0},
    "Birnin Kebbi": {"villages": 457, "people": 342703, "under5": 67062, "dark": 284, "lon": 4.2, "lat": 12.45},
}
HISTORY = {
    "Bunza": [{"event_type": "flood", "zone_name": "2024 rainy-season floods",
               "metrics": {"event_date": "2024-09-01", "source": "IOM DTM / NEMA",
                           "source_url": "https://example.org/report"}}],
}


def test_one_row_per_lga_heaviest_first():
    rows = _merge_impact(ADV, STORMS, EXPOSURE, HISTORY)
    assert [r.lga for r in rows] == ["Bunza", "Arewa Dandi", "Birnin Kebbi"]


def test_keeps_the_heaviest_storm_of_the_day():
    bunza = _merge_impact(ADV, STORMS, EXPOSURE, HISTORY)[0]
    assert bunza.storm is not None and bunza.storm.total_mm == 82.53
    assert bunza.storm.percentile_3h == 96.3


def test_carries_exposure_history_and_the_sms():
    bunza = _merge_impact(ADV, STORMS, EXPOSURE, HISTORY)[0]
    assert (bunza.people, bunza.under5, bunza.villages, bunza.dark_villages) == (193002, 38906, 480, 436)
    assert bunza.sms_recipients == 11 and bunza.rain_day_mm == 101.56
    assert bunza.history[0].source == "IOM DTM / NEMA"


def test_location_prefers_the_storm_then_villages_then_centroid():
    rows = {r.lga: r for r in _merge_impact(ADV, STORMS, EXPOSURE, HISTORY, lambda lga: (9.9, 9.9))}
    assert (rows["Bunza"].location.lon, rows["Bunza"].location.lat) == (4.02, 12.1)
    assert (rows["Birnin Kebbi"].location.lon, rows["Birnin Kebbi"].location.lat) == (4.2, 12.45)
    only_centroid = _merge_impact([{"lga": "Suru", "rain_mm_day": 47.6}], [], {}, {}, lambda lga: (4.1, 11.9))
    assert (only_centroid[0].location.lon, only_centroid[0].location.lat) == (4.1, 11.9)


def test_an_lga_with_no_village_layer_reports_zero_not_a_guess():
    rows = {r.lga: r for r in _merge_impact(ADV, STORMS, EXPOSURE, HISTORY)}
    assert rows["Arewa Dandi"].people == 0 and rows["Arewa Dandi"].villages == 0


def test_no_rain_no_rows():
    assert _merge_impact([], [], {}, {}) == []
