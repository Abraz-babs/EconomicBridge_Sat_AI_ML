"""IATI (d-portal) aid activities — the rules that decide what counts, DB-free.

Every case here is a pattern seen in the live Nigeria corpus on 2026-09-25.
"""
from __future__ import annotations

from datetime import date

from sources.iati_dportal import (
    EXCLUDED_REPORTERS, IatiLocation, assemble, day, is_current, is_national,
    named_states, sector_buckets, sector_names,
)
from tasks.aid_iati_ingest import place, plan_rows, state_centre

TODAY = date(2026, 9, 25)


def _loc(name=None, lon=4.52, lat=12.74, shared=1, start=date(2023, 1, 1),
         end=date(2027, 12, 31), aid="XM-DAC-41122-1", groups=("140",)):
    return IatiLocation(iati_id=aid, org_name="UNICEF", org_ref="XM-DAC-41122",
                        title="WASH", sector_groups=groups, start=start, end=end,
                        lon=lon, lat=lat, location_name=name, shared=shared)


# ─── current ─────────────────────────────────────────────────────────────

def test_status_alone_does_not_make_an_activity_current():
    assert not is_current(date(2011, 3, 21), None, TODAY)        # stale "implementation"
    assert not is_current(date(2019, 1, 1), date(2023, 12, 20), TODAY)
    assert not is_current(date(2027, 1, 1), date(2029, 1, 1), TODAY)   # not started
    assert is_current(date(2026, 1, 2), date(2029, 1, 1), TODAY)
    assert is_current(date(2024, 6, 1), None, TODAY)             # recent, open-ended


def test_dportal_days_are_days_since_1970():
    assert day(20721) == TODAY and day(None) is None and day(0) is None


# ─── what a location name means ──────────────────────────────────────────

def test_state_labels_are_recognised():
    assert named_states("Kebbi State") == {"kebbi"}
    assert named_states("Zamfara") == {"zamfara"}
    assert named_states("NG - Adamawa-Bauchi-Kebbi") == {"adamawa", "bauchi", "kebbi"}
    assert named_states("Federal Capital Territory") == {"fct"}
    assert named_states("Nassarawa State") == {"nasarawa"}


def test_places_are_not_state_labels():
    assert named_states("Argungu") == frozenset()
    assert named_states("Kaduna Road Clinic") == frozenset()
    assert named_states("Niger Delta") == frozenset()        # a region, not Niger State
    assert named_states(None) == frozenset()


def test_national_locations():
    assert is_national(_loc("Nigeria"))
    assert is_national(_loc(None, lon=8.675, lat=9.082))      # Nigeria centre point
    assert is_national(_loc(None, lon=7.399, lat=9.076, shared=224))   # Abuja head offices
    assert not is_national(_loc(None, lon=7.399, lat=9.076, shared=1)) # one real Abuja site


# ─── placing a location in a tenant ──────────────────────────────────────

def test_a_real_site_lands_in_its_lga():
    assert place("kebbi", _loc("Argungu"), state_centre("kebbi")) == (True, "Argungu")


def test_a_state_label_is_statewide_for_that_state_only():
    loc = _loc("NG - Adamawa-Bauchi-Kebbi", lon=3.93, lat=11.33)
    assert place("kebbi", loc, state_centre("kebbi")) == (True, None)
    assert place("zamfara", loc, state_centre("zamfara")) == (False, None)


def test_a_busy_state_centre_pin_is_statewide_but_a_busy_lga_pin_is_a_site():
    centre = state_centre("zamfara")
    assert place("zamfara", _loc(None, lon=6.247, lat=12.102, shared=232), centre) == (True, None)
    mine, lga = place("zamfara", _loc(None, lon=6.771, lat=12.83, shared=70), centre)
    assert mine and lga == "Zurmi"


def test_national_programmes_are_not_counted_in_a_state():
    assert place("fct", _loc("Abuja", lon=7.495, lat=9.058, shared=142), state_centre("fct"))[0] is False
    assert place("nasarawa", _loc("Nigeria", lon=8.675, lat=9.082, shared=117),
                 state_centre("nasarawa"))[0] is False


def test_national_programmes_are_countrywide_for_a_country_tenant():
    assert place("ghana", _loc("Ghana", lon=-1.0, lat=8.0), state_centre("ghana")) == (True, None)


def test_plan_rows_keeps_only_current_activities_in_the_tenant():
    rows = plan_rows("kebbi", [
        _loc("Argungu", aid="A1"),
        _loc("Argungu", aid="A2", start=date(2011, 1, 1), end=None),   # stale
        _loc("Gusau", lon=6.66, lat=12.16, aid="A3"),                  # Zamfara
    ], TODAY)
    assert [(r.iati_id, r.lga) for r in rows] == [("A1", "Argungu")]
    assert rows[0].sectors == "Water & sanitation"


# ─── assembling d-portal's three result sets ─────────────────────────────

def test_assemble_joins_sectors_counts_shared_pins_and_drops_aiddata():
    acts = [
        {"aid": "A1", "title": "WASH", "reporting": "UNICEF", "reporting_ref": "XM-DAC-41122",
         "day_start": 19358, "day_end": 21183},
        {"aid": "D1", "title": "Old", "reporting": "AidData",
         "reporting_ref": next(iter(EXCLUDED_REPORTERS)), "day_start": 15000, "day_end": None},
    ]
    locs = [
        {"aid": "A1", "location_name": "Argungu", "location_longitude": 4.52, "location_latitude": 12.74},
        {"aid": "A1", "location_name": "Argungu", "location_longitude": 4.52, "location_latitude": 12.74},
        {"aid": "D1", "location_name": "Kebbi State", "location_longitude": 4.52, "location_latitude": 12.74},
        {"aid": "A1", "location_name": "bad", "location_longitude": None, "location_latitude": 1},
    ]
    secs = [{"aid": "A1", "sector_group": "140"}, {"aid": "A1", "sector_group": "112"}]
    (only,) = assemble(acts, locs, secs)
    assert only.iati_id == "A1" and only.sector_groups == ("112", "140")
    assert only.shared == 3            # every published row at that coordinate counts
    assert only.start == date(2023, 1, 1)


def test_sector_names_and_overlap_buckets():
    assert sector_names(("112", "140")) == ["Basic education", "Water & sanitation"]
    assert sector_buckets(("121", "122")) == ["Health"]
    assert sector_buckets(()) == ["Other"]
