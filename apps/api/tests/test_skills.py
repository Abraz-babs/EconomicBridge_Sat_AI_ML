"""Tests for Module 07 (SkillsBridge) — Slice 08."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers.skills import _connectivity_band
from scripts.seed_skills_indicators import (
    LGA_POOL,
    SEED_SOURCE,
    TENANT_SKILLS_PROFILE,
    _hash_unit,
    _rows_for,
)


client = TestClient(app)


# ─── _connectivity_band ───────────────────────────────────────────────────


def test_connectivity_band_no_signal():
    assert _connectivity_band(0) == "no_signal"
    assert _connectivity_band(9.9) == "no_signal"


def test_connectivity_band_limited():
    assert _connectivity_band(10) == "limited"
    assert _connectivity_band(29.9) == "limited"


def test_connectivity_band_basic():
    assert _connectivity_band(30) == "basic"
    assert _connectivity_band(59.9) == "basic"


def test_connectivity_band_broadband():
    assert _connectivity_band(60) == "broadband"
    assert _connectivity_band(98) == "broadband"


# ─── Seed determinism ─────────────────────────────────────────────────────


def test_hash_unit_in_zero_one_range():
    v = _hash_unit("kebbi", "Argungu", "net")
    assert 0.0 <= v < 1.0


def test_hash_unit_is_deterministic():
    a = _hash_unit("kebbi", "Argungu", "net")
    b = _hash_unit("kebbi", "Argungu", "net")
    assert a == b


def test_hash_unit_differs_across_salts():
    """Same tenant+LGA but different metric salt → different values."""
    net = _hash_unit("kebbi", "Argungu", "net")
    power = _hash_unit("kebbi", "Argungu", "power")
    assert net != power


def test_rows_for_returns_eight_per_pilot_state():
    """8 LGAs in LGA_POOL × all states except FCT (6) = expected count."""
    for tenant in ("kebbi", "benue", "ghana", "senegal"):
        rows = _rows_for(tenant)
        assert len(rows) == 8


def test_rows_for_returns_six_lgas_for_fct():
    rows = _rows_for("fct")
    assert len(rows) == 6


def test_rows_for_anchored_to_tenant_centroid():
    """LGA points fan around the tenant centroid within ~1°."""
    rows = _rows_for("kebbi")
    centroid_lon, centroid_lat = (4.55, 12.00)
    for r in rows:
        assert abs(r.lon - centroid_lon) < 1.2
        assert abs(r.lat - centroid_lat) < 1.2


def test_rows_for_internet_coverage_tracks_tenant_anchor():
    """All LGAs in a tenant cluster around the anchor ± spread/2."""
    for tenant, (anchor, _spread, _density, _power) in TENANT_SKILLS_PROFILE.items():
        rows = _rows_for(tenant)
        net_values = [r.internet_coverage_pct for r in rows]
        mean = sum(net_values) / len(net_values)
        # Mean should be within ~50% of the anchor across 6-8 LGAs.
        assert abs(mean - anchor) < max(15.0, anchor * 0.50), \
            f"{tenant}: mean={mean} anchor={anchor}"


def test_rows_for_fct_has_better_connectivity_than_kebbi():
    """Capital region has higher mean internet coverage than rural north.
    Pin this so a refactor doesn't accidentally decouple the anchors."""
    fct_rows = _rows_for("fct")
    kebbi_rows = _rows_for("kebbi")
    fct_mean = sum(r.internet_coverage_pct for r in fct_rows) / len(fct_rows)
    kebbi_mean = sum(r.internet_coverage_pct for r in kebbi_rows) / len(kebbi_rows)
    assert fct_mean > kebbi_mean


def test_rows_for_mobile_runs_higher_than_internet():
    """2G blanket is wider than internet — mobile should always >= internet."""
    for tenant in ("kebbi", "fct", "ghana"):
        for r in _rows_for(tenant):
            assert r.mobile_coverage_pct >= r.internet_coverage_pct


def test_rows_for_scores_bounded():
    for tenant in ("kebbi", "fct", "ghana"):
        for r in _rows_for(tenant):
            assert 0.0 <= r.electricity_reliability <= 1.0
            assert 0.0 <= r.learning_gap_index <= 1.0
            assert 0.0 <= r.internet_coverage_pct <= 100.0
            assert 0.0 <= r.mobile_coverage_pct <= 100.0


def test_rows_for_school_count_positive():
    for r in _rows_for("kebbi"):
        assert r.school_count > 0


def test_rows_for_kebbi_gap_worse_than_fct():
    """Higher gap index = worse infra. Kebbi rural should score worse."""
    fct_gap = sum(r.learning_gap_index for r in _rows_for("fct")) / 6
    kebbi_gap = sum(r.learning_gap_index for r in _rows_for("kebbi")) / 8
    assert kebbi_gap > fct_gap


def test_rows_for_lgas_match_pool():
    for tenant, pool in LGA_POOL.items():
        seen = {r.lga for r in _rows_for(tenant)}
        assert seen == set(pool)


def test_rows_for_is_deterministic():
    a = _rows_for("kebbi")
    b = _rows_for("kebbi")
    assert a == b


def test_seed_source_constant_is_v1():
    assert SEED_SOURCE == "seed_v1"


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_indicators_endpoint_without_tenant_header_returns_400():
    r = client.get("/api/v1/skills/indicators")
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_indicators_endpoint_with_unknown_tenant_returns_404():
    r = client.get(
        "/api/v1/skills/indicators",
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert r.status_code == 404


def test_indicators_endpoint_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/skills/indicators"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 200


def test_skills_stats_data_has_all_aggregate_fields():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["SkillsStatsData"]
    props = schema["properties"]
    expected = {
        "tenant_id", "total_lgas", "median_internet_coverage_pct",
        "median_school_density", "total_schools", "total_youth_population",
        "best_connectivity_lga", "worst_gap_lga", "most_underserved_lga",
        "most_schools_lga", "indicators", "sources",
    }
    assert expected <= set(props.keys())


def test_connectivity_band_enum_locked():
    spec = client.get("/api/openapi.json").json()
    schemas = spec["components"]["schemas"]
    indicator = schemas["SkillsIndicatorRow"]
    field = indicator["properties"]["connectivity_band"]
    enum: list[str]
    if "$ref" in field:
        ref = field["$ref"].split("/")[-1]
        enum = schemas[ref]["enum"]
    else:
        enum = field.get("enum", [])
    assert set(enum) == {"no_signal", "limited", "basic", "broadband"}
