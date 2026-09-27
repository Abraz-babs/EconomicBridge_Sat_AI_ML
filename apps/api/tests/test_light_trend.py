"""Mobility Compass night-light trend — the rules in _classify_lga and _build_light_lgas."""
from __future__ import annotations

from routers.economic_mobility import _build_light_lgas, _classify_lga


def _s(start, end, n=14):
    return [start] * 3 + [start] * (n - 6) + [end] * 3


def test_dimmer_when_both_composites_fall():
    cat, pct = _classify_lga(_s(277.0, 5.5), _s(300.0, 12.0))
    assert cat == "dimmer" and round(pct) == -98


def test_mixed_when_composites_disagree():
    cat, pct = _classify_lga(_s(30.8, 17.1), _s(40.0, 52.8))       # Tsafe: -45% / +32%
    assert cat == "mixed" and round(pct) == -44


def test_steady_when_both_barely_move():
    assert _classify_lga(_s(100.0, 105.0), _s(120.0, 110.0))[0] == "steady"


def test_small_start_gets_no_percentage():
    # Gummi: 0.6 -> 14.3 is "new light", never "+2424%"
    assert _classify_lga(_s(0.6, 14.3), _s(0.9, 20.0)) == ("new_light", None)
    assert _classify_lga(_s(0.2, 0.7), _s(0.3, 1.1)) == ("still_dark", None)


def test_new_light_on_one_and_big_rise_on_other_is_brighter():
    cat, _ = _classify_lga(_s(4.2, 11.0), _s(1.5, 9.0))            # pct +162% / new
    assert cat == "brighter"


def test_faint_on_one_but_lit_on_other_is_mixed():
    # Bukkuyum: still dark on near-nadir, new light on all-angle
    assert _classify_lga(_s(0.2, 1.5), _s(0.3, 7.0))[0] == "mixed"


def test_missing_series_is_mixed():
    assert _classify_lga([None] * 14, _s(10.0, 20.0))[0] == "mixed"


def _rows(lga, near, allang, lit=1.0):
    out = []
    for i, (a, b) in enumerate(zip(near, allang)):
        out.append({"lga": lga, "year": 2012 + i, "composite": "near_nadir", "radiance_sum": a, "lit_km2": lit})
        out.append({"lga": lga, "year": 2012 + i, "composite": "all_angle", "radiance_sum": b, "lit_km2": lit})
    return out


def test_build_orders_dimmest_first_and_carries_villages():
    rows = _rows("Bakura", _s(277.0, 5.5), _s(300.0, 12.0)) + _rows("Gusau", _s(1200.0, 1383.0), _s(1500.0, 1950.0))
    villages = {"Bakura": {"people": 175888, "villages": 489, "gone_dark": 92, "newly_lit": 0}}
    lgas, first, last = _build_light_lgas(rows, villages, lambda lga: (6.0, 12.3))
    assert (first, last) == (2012, 2025)
    assert [g.lga for g in lgas] == ["Bakura", "Gusau"]
    b = lgas[0]
    assert b.category == "dimmer" and b.gone_dark == 92 and b.people == 175888
    assert len(b.near_nadir) == 14 and b.location is not None
    assert lgas[1].category == "brighter" and lgas[1].people == 0


def test_build_empty():
    assert _build_light_lgas([], {}) == ([], 0, 0)
