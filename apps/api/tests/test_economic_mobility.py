"""Tests for Module 06 (Economic Mobility Compass) — Slice 07."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers.economic_mobility import _col_band
from scripts.seed_mobility_indicators import (
    LGA_POOL,
    SEED_SOURCE,
    TENANT_COL_PROFILE,
    _hash_unit,
    _rows_for,
)


client = TestClient(app)


# ─── _col_band ────────────────────────────────────────────────────────────


def test_col_band_below_avg():
    assert _col_band(70) == "below_avg"
    assert _col_band(84) == "below_avg"


def test_col_band_near_avg():
    assert _col_band(85) == "near_avg"
    assert _col_band(100) == "near_avg"
    assert _col_band(109) == "near_avg"


def test_col_band_above_avg():
    assert _col_band(110) == "above_avg"
    assert _col_band(139) == "above_avg"


def test_col_band_premium():
    assert _col_band(140) == "premium"
    assert _col_band(180) == "premium"


# ─── Seed determinism ─────────────────────────────────────────────────────


def test_hash_unit_in_zero_one_range():
    v = _hash_unit("kebbi", "Argungu", "col")
    assert 0.0 <= v < 1.0


def test_hash_unit_is_deterministic():
    a = _hash_unit("kebbi", "Argungu", "col")
    b = _hash_unit("kebbi", "Argungu", "col")
    assert a == b


def test_hash_unit_differs_across_salts():
    """Same tenant+LGA but different metric salt → different values."""
    col = _hash_unit("kebbi", "Argungu", "col")
    income = _hash_unit("kebbi", "Argungu", "income")
    assert col != income


def test_rows_for_returns_one_row_per_official_lga():
    """One row per LGA in the tenant's official set (services.lga_geo). The
    old 8-per-state cap was removed in 6e51d81, so the count now tracks
    all_lgas()."""
    from services.lga_geo import all_lgas
    for tenant in ("kebbi", "benue", "ghana", "senegal"):
        rows = _rows_for(tenant)
        assert len(rows) == len(all_lgas(tenant)) > 0


def test_rows_for_returns_six_lgas_for_fct():
    rows = _rows_for("fct")
    assert len(rows) == 6


def test_rows_for_use_real_lga_centroids():
    """Each row's coords must come from services.lga_geo (not a synthetic
    fan). Pin a known LGA to its hand-curated centroid so a regression
    that re-introduces the fan would fail loudly."""
    from services.lga_geo import centroid_for
    rows = _rows_for("kebbi")
    argungu = next(r for r in rows if r.lga == "Argungu")
    expected_lon, expected_lat = centroid_for("kebbi", "Argungu")
    assert argungu.lon == expected_lon
    assert argungu.lat == expected_lat


def test_fct_lga_coords_stay_inside_fct_bounds():
    """The original 8-direction fan placed FCT LGAs into southern Kaduna
    (lat > 9.4°N). Real centroids must stay within FCT bounds."""
    fct_min_lon, fct_max_lon = 6.7, 7.7
    fct_min_lat, fct_max_lat = 8.4, 9.4
    for r in _rows_for("fct"):
        assert fct_min_lon <= r.lon <= fct_max_lon, f"{r.lga} lon={r.lon}"
        assert fct_min_lat <= r.lat <= fct_max_lat, f"{r.lga} lat={r.lat}"


def test_rows_for_cost_of_living_tracks_tenant_anchor():
    """All LGAs in a tenant cluster around the anchor ± spread/2."""
    for tenant, (anchor, spread) in TENANT_COL_PROFILE.items():
        rows = _rows_for(tenant)
        col_values = [r.cost_of_living_index for r in rows]
        mean = sum(col_values) / len(col_values)
        # Mean should be within 30% of the anchor across 6-8 LGAs.
        assert abs(mean - anchor) < anchor * 0.30, f"{tenant}: mean={mean} anchor={anchor}"


def test_rows_for_income_correlates_with_cost_of_living():
    """Capital regions have BOTH higher COL and higher avg income.
    Pin this so a future refactor doesn't accidentally decouple them."""
    fct_rows = _rows_for("fct")
    kebbi_rows = _rows_for("kebbi")
    fct_mean_income = sum(r.avg_household_income_ngn for r in fct_rows) / len(fct_rows)
    kebbi_mean_income = sum(r.avg_household_income_ngn for r in kebbi_rows) / len(kebbi_rows)
    assert fct_mean_income > kebbi_mean_income


def test_rows_for_scores_bounded_zero_to_one():
    for tenant in ("kebbi", "fct", "ghana"):
        for r in _rows_for(tenant):
            assert 0.0 <= r.income_opportunity_score <= 1.0
            assert 0.0 <= r.displacement_capacity_index <= 1.0


def test_rows_for_population_is_positive():
    for r in _rows_for("kebbi"):
        assert r.population > 0


def test_rows_for_lgas_match_official_set():
    """Seeded LGAs come from services.lga_geo (the official per-state set),
    not the legacy LGA_POOL fallback."""
    from services.lga_geo import all_lgas
    for tenant in LGA_POOL:
        seen = {r.lga for r in _rows_for(tenant)}
        assert seen == set(all_lgas(tenant))


def test_rows_for_is_deterministic():
    a = _rows_for("kebbi")
    b = _rows_for("kebbi")
    assert a == b


def test_seed_source_constant_is_v1():
    assert SEED_SOURCE == "seed_v1"


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_indicators_endpoint_without_tenant_header_returns_400():
    r = client.get("/api/v1/economic_mobility/indicators")
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_indicators_endpoint_with_unknown_tenant_returns_404():
    r = client.get(
        "/api/v1/economic_mobility/indicators",
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert r.status_code == 404


def test_indicators_endpoint_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/economic_mobility/indicators"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 2000


def test_mobility_stats_data_has_all_aggregate_fields():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["MobilityStatsData"]
    props = schema["properties"]
    expected = {
        "tenant_id", "total_lgas", "median_cost_of_living",
        "median_household_income_ngn", "cheapest_lga", "most_expensive_lga",
        "best_opportunity_lga", "best_capacity_lga", "indicators", "sources",
    }
    assert expected <= set(props.keys())


def test_compare_band_enum_locked():
    spec = client.get("/api/openapi.json").json()
    # CompareBand may be inlined or $ref'd by Pydantic depending on usage.
    schemas = spec["components"]["schemas"]
    indicator = schemas["MobilityIndicatorRow"]
    field = indicator["properties"]["cost_of_living_band"]
    enum: list[str]
    if "$ref" in field:
        ref = field["$ref"].split("/")[-1]
        enum = schemas[ref]["enum"]
    else:
        enum = field.get("enum", [])
    assert set(enum) == {"below_avg", "near_avg", "above_avg", "premium"}
