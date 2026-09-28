"""Mobility Compass (2026-09-28): the rules behind each factor, without a database.

Signals are a count of readings that point to pressure — never a score. Travel
time is people-weighted. Prices come from the best-evidenced series, and a
model estimate is always labelled as one.
"""
from __future__ import annotations

from datetime import date

from routers.economic_mobility import (
    SIGNAL_FADING,
    SIGNAL_FAR,
    SIGNAL_FARM_BEHIND,
    SIGNAL_FARM_FLAT,
    _access_by_lga,
    _month_floor,
    _pick_prices,
    _signals,
    _wquantile,
)
from routers.reports import REPORT_SPECS, UNLISTED_REPORTS

TODAY = date(2026, 9, 28)


# ─── signals ─────────────────────────────────────────────────────────────


def test_all_three_signals_when_every_reading_points_the_same_way():
    assert _signals("dimmer", -4.0, 0.62) == [SIGNAL_FADING, SIGNAL_FARM_BEHIND, SIGNAL_FAR]


def test_farming_flat_is_under_five_percent_not_just_a_fall():
    assert _signals(None, 3.9, None) == [SIGNAL_FARM_FLAT]
    assert _signals(None, 5.0, None) == []


def test_no_reading_is_no_signal():
    # A missing measurement must never count as pressure.
    assert _signals(None, None, None) == []
    assert _signals("mixed", None, 0.49) == []


def test_brighter_light_is_not_a_signal():
    assert _signals("brighter", 20.0, 0.1) == []


# ─── travel time ─────────────────────────────────────────────────────────


def test_weighted_median_follows_people_not_villages():
    # Three hamlets far away, one town close: the median person is in the town.
    assert _wquantile([200, 210, 220, 20], [10, 10, 10, 5000], 0.5) == 20


def test_weighted_quantile_with_nobody_is_none():
    assert _wquantile([10, 20], [0, 0], 0.5) is None


def test_share_is_over_people_with_a_travel_time():
    rows = [
        {"lga": "A", "people": 1000, "walk_min": 90.0, "drive_min": 20.0},
        {"lga": "A", "people": 1000, "walk_min": 30.0, "drive_min": 10.0},
        # no travel time here: counted in people, not in the share
        {"lga": "A", "people": 8000, "walk_min": None, "drive_min": None},
    ]
    a = _access_by_lga(rows)["A"]
    assert a["people"] == 10000
    assert a["over_hour_walk_people"] == 1000
    assert a["over_hour_walk_share"] == 0.5


def test_exactly_an_hour_is_not_over_an_hour():
    a = _access_by_lga([{"lga": "B", "people": 50, "walk_min": 60.0, "drive_min": None}])["B"]
    assert a["over_hour_walk_people"] == 0
    assert a["drive_median_min"] is None


# ─── prices ──────────────────────────────────────────────────────────────


def _wb(adm1, market, item, months, price=100.0):
    return [{"adm1": adm1, "market": market, "item": item,
             "observed_at": _month_floor(TODAY, m), "price_ngn": price + m} for m in months]


def test_recently_surveyed_market_beats_everything():
    wb = _wb("Zamfara", "Kaura Namoda", "maize", range(0, 36)) + \
        _wb("Geopolitical Zone", "North West", "maize", range(0, 36))
    surveyed = {("Zamfara", "Kaura Namoda", "maize"): date(2026, 6, 1),
                ("Geopolitical Zone", "North West", "maize"): date(2026, 5, 1)}
    maize = [p for p in _pick_prices("zamfara", wb, surveyed, [], TODAY) if p.item == "maize"][0]
    assert maize.place == "Kaura Namoda market"
    assert maize.modelled and maize.publisher == "World Bank"
    assert maize.last_surveyed == date(2026, 6, 1)


def test_never_surveyed_market_gives_way_to_a_surveyed_zone_average():
    # Kebbi's Gwandu market has never had food surveyed: its series is pure model.
    wb = _wb("Kebbi", "Gwandu", "maize", range(0, 36)) + \
        _wb("Geopolitical Zone", "North West", "maize", range(0, 36))
    surveyed = {("Geopolitical Zone", "North West", "maize"): date(2026, 5, 1)}
    maize = [p for p in _pick_prices("kebbi", wb, surveyed, [], TODAY) if p.item == "maize"][0]
    assert maize.place == "North West average"


def test_stale_published_prices_beat_unsurveyed_estimates_and_say_they_are_stale():
    published = [{"crop": "millet", "source": "fews_market_v1", "month": date(2024, m, 28),
                  "price_ngn_per_kg": 500.0 + m} for m in range(1, 13)]
    wb = _wb("Kebbi", "Gwandu", "sorghum", range(0, 36))
    out = {p.item: p for p in _pick_prices("kebbi", wb, {}, published, TODAY)}
    assert out["millet"].publisher == "FEWS NET" and out["millet"].stale
    assert not out["millet"].modelled
    assert out["sorghum"].modelled and out["sorghum"].last_surveyed is None


def test_current_tiles_come_before_stale_ones():
    published = [{"crop": "maize", "source": "fews_market_v1", "month": date(2024, 12, 31),
                  "price_ngn_per_kg": 400.0}]
    wb = _wb("Geopolitical Zone", "North West", "rice", range(0, 36))
    surveyed = {("Geopolitical Zone", "North West", "rice"): date(2026, 5, 1)}
    items = [p.item for p in _pick_prices("kaduna", wb, surveyed, published, TODAY) if p.item != "petrol"]
    assert items == ["rice", "maize"]


def test_petrol_is_twelve_months_of_model_estimate():
    wb = _wb("Kaduna", "Giwa", "petrol", range(0, 36), price=900.0)
    petrol = _pick_prices("kaduna", wb, {("Kaduna", "Giwa", "petrol"): date(2023, 1, 1)}, [], TODAY)[0]
    assert petrol.item == "petrol" and petrol.unit == "litre"
    assert petrol.modelled
    assert len(petrol.points) == 13          # a 12-month change needs both ends
    assert petrol.last_surveyed == date(2023, 1, 1)


def test_state_without_a_market_gets_the_all_market_petrol_average():
    wb = _wb("Market Average", "Market Average", "petrol", range(0, 20), price=950.0)
    petrol = _pick_prices("niger", wb, {}, [], TODAY)[0]
    assert petrol.place == "average of the World Bank's markets"


def test_no_prices_for_a_pilot_outside_nigeria():
    wb = _wb("Market Average", "Market Average", "petrol", range(0, 20))
    assert _pick_prices("ghana", wb, {}, [], TODAY) == []


# ─── reports read what the pages show ───────────────────────────────────


def test_mobility_and_skills_reports_are_listed_again_on_measured_views():
    assert "mobility-compass" not in UNLISTED_REPORTS
    assert REPORT_SPECS["mobility-compass"].table == "mobility_villages"
    assert REPORT_SPECS["skillsbridge"].table == "school_reach"


def test_reports_never_include_rows_the_pages_hide():
    assert "-seed" in (REPORT_SPECS["cropguard"].real_only or "")
    shock = REPORT_SPECS["shockguard"].real_only or ""
    assert "synthetic" in shock and "seed_v1" in shock


def test_every_report_metric_column_is_exported_or_derived_from_the_view():
    for key in ("mobility-compass", "skillsbridge"):
        spec = REPORT_SPECS[key]
        assert spec.date_col in spec.columns
