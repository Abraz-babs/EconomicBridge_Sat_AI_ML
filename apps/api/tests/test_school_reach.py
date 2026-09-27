"""SkillsBridge school reach list — the rules in _build_reach."""
from __future__ import annotations

from routers.skills import GRID3_STATE, _build_reach


def _school(name, *, lga="Shanga", village="V", sid=1, people=100, under5=20,
            lit=0, unlit=1, category="Primary", km=0.5):
    return {
        "name": name, "category": category, "management": "Public", "lga": lga,
        "lon": 4.5, "lat": 11.2, "settlement_id": sid, "village": village, "ward": "W",
        "village_light": "unlit" if lit == 0 else "lit", "people": people, "under5": under5,
        "village_km": km, "villages_2km": lit + unlit, "lit_2km": lit, "unlit_2km": unlit,
        "people_2km": people * 2, "under5_2km": under5 * 2,
    }


def test_dark_only_when_no_village_within_2km_is_lit():
    out = _build_reach([
        _school("A", lit=0, unlit=3),
        _school("B", lit=1, unlit=4, sid=2),     # one lit quarter nearby -> not dark
    ])
    light = {s.name: s.light for s in out["rows"]}
    assert light == {"A": "dark", "B": "lit"}
    assert out["dark"] == 1 and out["assessed"] == 2 and out["dark_pct"] == 50.0


def test_no_village_within_2km_is_unknown_and_not_counted():
    row = _school("Far", lit=0, unlit=0)
    row["village"] = None
    out = _build_reach([row, _school("Near", sid=2)])
    assert [s.light for s in out["rows"]] == ["unknown", "dark"]
    assert out["schools"] == 2 and out["assessed"] == 1 and out["dark_pct"] == 100.0


def test_reach_list_is_one_school_per_village_most_people_first():
    out = _build_reach([
        _school("Small village school", sid=1, people=300),
        _school("Big village primary", sid=2, people=9000),
        _school("Big village secondary", sid=2, people=9000, category="Secondary"),
        _school("Lit town school", sid=3, people=50000, lit=2),
    ])
    ranked = sorted((s for s in out["rows"] if s.rank), key=lambda s: s.rank)
    assert [s.name for s in ranked] == ["Big village primary", "Small village school"]
    # people are counted once per village, not once per school
    assert out["dark_villages"] == 2 and out["people"] == 9300 and out["under5"] == 40


def test_lgas_roll_up_darkest_first():
    out = _build_reach([
        _school("a", lga="Argungu", sid=1, lit=1),
        _school("b", lga="Argungu", sid=2),
        _school("c", lga="Shanga", sid=3),
    ])
    assert [(g.lga, g.schools, g.dark, g.dark_pct) for g in out["lgas"]] == [
        ("Shanga", 1, 1, 100.0), ("Argungu", 2, 1, 50.0),
    ]


def test_counts_primary_and_secondary():
    out = _build_reach([_school("p"), _school("s", category="Secondary", sid=2)])
    assert out["primary"] == 1 and out["secondary"] == 1


def test_empty_state_has_no_share():
    out = _build_reach([])
    assert out["schools"] == 0 and out["dark_pct"] is None and out["rows"] == []


def test_every_nigerian_pilot_maps_to_a_grid3_state():
    assert set(GRID3_STATE) == {"kebbi", "zamfara", "niger", "kaduna", "benue",
                                "plateau", "nasarawa", "fct"}
    assert GRID3_STATE["fct"] == "Fct"
