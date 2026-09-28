"""Mobility Compass factor loaders (2026-09-28), tested without network or database.

* World Bank real-time prices: surveyed and modelled prices are kept apart.
* Travel time: raster pixels are found by hand, no-data is never a time.
* GRID3 health facilities: a facility without coordinates is kept, not placed.
"""
from __future__ import annotations

import inspect

import numpy as np

from scripts.load_grid3_health_facilities import RELEASES, parse_feature
from tasks.market_prices_ingest import ESTIMATE, FOOD_ITEMS, SURVEY, parse_rtp
from tasks.village_access import pixel_index, to_minutes

HEAD = ("ISO3,country,adm1_name,adm2_name,mkt_name,lat,lon,geo_id,DATES,year,month,currency,"
        "spatially_interpolated,maize_fao,o_maize_fao,h_maize_fao,l_maize_fao,c_maize_fao")


def _csv(*rows: str) -> list[str]:
    return [HEAD + "\n", *(r + "\n" for r in rows)]


# ─── World Bank real-time prices ─────────────────────────────────────────


def test_survey_and_estimate_are_separate_rows():
    rows = list(parse_rtp(_csv(
        "NGA,Nigeria,Zamfara,Kaura Namoda,Kaura Namoda,12.6,6.6,g,2026-06-01,2026,6,NGN,0,381.83,527.02,530,500,514.88",
    ), FOOD_ITEMS))
    by = {r["source"]: r for r in rows}
    assert by[SURVEY]["price"] == 381.83          # what the market was surveyed at
    assert by[ESTIMATE]["price"] == 514.88        # the model's month close, not open
    assert by[ESTIMATE]["market"] == "Kaura Namoda" and by[ESTIMATE]["item"] == "maize"


def test_month_without_a_survey_keeps_only_the_estimate():
    rows = list(parse_rtp(_csv(
        "NGA,Nigeria,Zamfara,Kaura Namoda,Kaura Namoda,12.6,6.6,g,2026-08-01,2026,8,NGN,0,,552.86,560,540,553.35",
    ), FOOD_ITEMS))
    assert [r["source"] for r in rows] == [ESTIMATE]


def test_states_outside_the_pilots_and_interpolated_points_are_skipped():
    rows = list(parse_rtp(_csv(
        "NGA,Nigeria,Lagos,Ikeja,Ikeja,6.6,3.3,g,2026-08-01,2026,8,NGN,0,,1,1,1,900",
        "NGA,Nigeria,Kebbi,Gwandu,Gwandu,12.5,4.6,g,2026-08-01,2026,8,NGN,1,,1,1,1,700",
        "NGA,Nigeria,Geopolitical Zone,Kano,North West,12,8.5,g,2026-08-01,2026,8,NGN,0,,1,1,1,610",
    ), FOOD_ITEMS))
    assert [(r["adm1"], r["market"]) for r in rows] == [("Geopolitical Zone", "North West")]


def test_blank_zero_and_bad_prices_are_dropped():
    rows = list(parse_rtp(_csv(
        "NGA,Nigeria,Kaduna,Giwa,Giwa,11.3,7.4,g,2026-08-01,2026,8,NGN,0,0,,,,n/a",
        "NGA,Nigeria,Kaduna,Giwa,Giwa,11.3,7.4,g,not-a-date,2026,8,NGN,0,5,,,,6",
    ), FOOD_ITEMS))
    assert rows == []


# ─── travel time rasters ─────────────────────────────────────────────────


def test_pixel_index_on_a_north_up_grid():
    # 0.01° pixels, origin (3.0 E, 14.0 N), 100 × 100.
    t = (0.01, 0.0, 3.0, 0.0, -0.01, 14.0)
    rr, cc, inside = pixel_index(np.array([3.005, 3.995]), np.array([13.995, 13.005]), t, 100, 100)
    assert rr.tolist() == [0, 99] and cc.tolist() == [0, 99]
    assert inside.all()


def test_points_off_the_grid_are_flagged_not_misread():
    t = (0.01, 0.0, 3.0, 0.0, -0.01, 14.0)
    rr, cc, inside = pixel_index(np.array([2.5, 3.5]), np.array([13.5, 15.0]), t, 100, 100)
    assert inside.tolist() == [False, False]
    assert (rr >= 0).all() and (cc >= 0).all()       # clamped for the read only


def test_seconds_become_minutes_and_no_data_is_never_a_time():
    m = to_minutes(np.array([3600.0, -9999.0, np.nan, np.inf, 90.0]))
    assert m[0] == 60.0 and m[4] == 1.5
    assert np.isnan(m[1:4]).all()


# ─── GRID3 health facilities ─────────────────────────────────────────────


def _feat(release: str, **attrs):
    geom = attrs.pop("geometry", {"x": 4.2, "y": 12.4})
    return {"attributes": attrs, "geometry": geom}


def test_v3_facility_parses_with_its_fields():
    row = parse_feature(_feat("v3.0", unique_id="SN_1", facility_name="PHC Birnin Kebbi",
                              facility_level="Primary", facility_type="PHC",
                              facility_ownership="Public", functional="Functional",
                              ward_standard="Nassarawa I", lga_standard="Birnin Kebbi"), "v3.0", "Kebbi")
    assert row["source_id"] == "SN_1" and row["level"] == "Primary"
    assert row["functional"] == "Functional" and (row["lon"], row["lat"]) == (4.2, 12.4)


def test_facility_without_coordinates_is_kept_unplaced():
    row = parse_feature(_feat("v3.0", unique_id="SN_2", facility_name="Health Post",
                              geometry=None), "v3.0", "Fct")
    assert row is not None
    assert row["lon"] is None and row["lat"] is None


def test_point_outside_nigeria_is_not_a_location():
    row = parse_feature(_feat("v2.0", globalid="{g}", facility_name="Clinic",
                              geometry={"x": 0.0, "y": 0.0}), "v2.0", "Benue")
    assert row["lon"] is None


def test_nameless_or_idless_rows_are_skipped():
    assert parse_feature(_feat("v2.0", globalid=None, facility_name="X"), "v2.0", "Benue") is None
    assert parse_feature(_feat("v2.0", globalid="g", facility_name=" "), "v2.0", "Benue") is None


def test_both_releases_cover_every_nigerian_pilot():
    covered = set(RELEASES["v3.0"]["states"].values()) | set(RELEASES["v2.0"]["states"].values())
    assert covered == {"Kebbi", "Zamfara", "Niger", "Kaduna", "Benue", "Plateau", "Nasarawa", "Fct"}
    # v3.0 does not publish Benue or Plateau, so v2.0 must.
    assert {"Benue", "Plateau"} <= set(RELEASES["v2.0"]["states"].values())


# ─── schedule ────────────────────────────────────────────────────────────


def test_market_price_job_is_monthly():
    from scheduler import JOB_ID_MARKET_PRICES_MONTHLY, setup_scheduler

    src = inspect.getsource(setup_scheduler)
    assert "run_market_price_ingest" in src and "JOB_ID_MARKET_PRICES_MONTHLY" in src
    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_MARKET_PRICES_MONTHLY)
        assert job is not None
        assert "day='17'" in str(job.trigger)
    finally:
        sched.remove_all_jobs()
