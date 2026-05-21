"""Tests for GET / POST /aid_coordination/coverage + seed determinism."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers.aid_coordination import _lga_centroid
from scripts.seed_aid_coordination import (
    AGENCY_REGISTRY,
    LGA_POOL,
    SEED_SOURCE,
    _coverage_for,
    _djb2,
    _Rng,
)


client = TestClient(app)


# ─── HTTP contract (DB-free) ──────────────────────────────────────────────


def test_get_coverage_without_tenant_header_returns_400():
    r = client.get("/api/v1/aid_coordination/coverage")
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_get_coverage_with_unknown_tenant_returns_404():
    r = client.get(
        "/api/v1/aid_coordination/coverage",
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert r.status_code == 404


def test_post_coverage_without_tenant_header_returns_400():
    r = client.post(
        "/api/v1/aid_coordination/coverage",
        json={"agency_slug": "wfp", "lga": "Argungu"},
    )
    assert r.status_code == 400


def test_post_coverage_request_declares_extra_forbid():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["AidCoverageUploadRequest"]
    assert schema.get("additionalProperties") is False


def test_post_coverage_endpoint_declares_field_constraints():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["AidCoverageUploadRequest"]
    props = schema["properties"]
    assert props["beneficiaries_served"]["minimum"] == 0
    assert props["beneficiaries_served"]["maximum"] == 10_000_000


# ─── Seed determinism ─────────────────────────────────────────────────────


def test_djb2_consistency_kebbi_and_ghana():
    """Pin against the same hashes as Slice 01.real so frontend
    + Module 01 backend + Module 02 backend stay aligned."""
    assert _djb2("kebbi") == 264785474
    assert _djb2("ghana") == 260148900


def test_rng_first_value_in_range():
    r = _Rng(_djb2("kebbi"))
    v = r.next()
    assert 0.0 <= v <= 1.0


def test_coverage_for_picks_five_to_eight_agencies():
    for tenant in ("kebbi", "benue", "senegal"):
        cov = _coverage_for(tenant)
        agency_slugs = {c.agency_slug for c in cov}
        assert 5 <= len(agency_slugs) <= 8, f"{tenant}: {len(agency_slugs)}"


def test_coverage_for_is_deterministic():
    a = _coverage_for("kebbi")
    b = _coverage_for("kebbi")
    assert a == b


def test_coverage_for_agency_slugs_are_in_registry():
    """Every agency the seed picks must exist in AGENCY_REGISTRY so
    the upload path's slug-validation check stays consistent."""
    registry_slugs = {a["slug"] for a in AGENCY_REGISTRY}
    cov = _coverage_for("plateau")
    seed_slugs = {c.agency_slug for c in cov}
    assert seed_slugs <= registry_slugs


def test_coverage_for_lgas_are_in_pool():
    """Every LGA the seed assigns must come from LGA_POOL for that tenant."""
    for tenant in ("kebbi", "ghana"):
        pool = set(LGA_POOL[tenant])
        cov_lgas = {c.lga for c in _coverage_for(tenant)}
        assert cov_lgas <= pool


def test_coverage_for_beneficiaries_non_negative():
    for c in _coverage_for("kebbi"):
        assert c.beneficiaries_served >= 0


def test_seed_source_constant_is_v1():
    assert SEED_SOURCE == "seed_v1"


# ─── LGA centroid math ────────────────────────────────────────────────────


def test_lga_centroid_returns_tenant_centre_for_zero_total():
    """Defensive: total=0 short-circuits to the tenant centre rather
    than dividing by zero."""
    lon, lat = _lga_centroid("kebbi", 0, 0)
    assert (lon, lat) == (4.55, 12.00)


def test_lga_centroid_spreads_around_tenant_centre():
    """8 LGAs around kebbi (centroid 4.55, 12.00) should all sit within
    ~1° of the centre."""
    points = [_lga_centroid("kebbi", i, 8) for i in range(8)]
    for lon, lat in points:
        assert abs(lon - 4.55) < 1.5
        assert abs(lat - 12.00) < 1.5


def test_lga_centroid_is_deterministic_per_index():
    a = _lga_centroid("benue", 3, 8)
    b = _lga_centroid("benue", 3, 8)
    assert a == b


def test_lga_centroid_unknown_tenant_falls_back_to_origin():
    """Unknown tenant lands at (0, 0) — deliberate sentinel."""
    lon, lat = _lga_centroid("atlantis", 0, 4)
    # idx 0 + total 4 → angle 0, radius 0.45
    assert lat == 0.0   # sin(0) = 0
