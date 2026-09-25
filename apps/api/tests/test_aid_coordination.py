"""Tests for GET / POST /aid_coordination/coverage + seed determinism."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers.aid_coordination import (
    _REAL_COVERAGE,
    SEED_SOURCE as READ_EXCLUDES,
    ActivityRow,
    build_stats,
)
from scripts.seed_aid_coordination import (
    AGENCY_REGISTRY,
    SEED_SOURCE,
    TENANT_COUNTRY,
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


def test_agencies_never_cross_borders():
    """Regression: a national agency (e.g. NEMA, Nigeria) must NOT appear in
    another country's coverage. Each tenant draws only international + its own
    national agencies."""
    scope = {a["slug"]: a["country"] for a in AGENCY_REGISTRY}
    for tenant, country in TENANT_COUNTRY.items():
        slugs = {c.agency_slug for c in _coverage_for(tenant)}
        for slug in slugs:
            assert scope[slug] in ("international", country), (
                f"{slug} ({scope[slug]}) leaked into {tenant} ({country})"
            )
    # Specifically: NEMA never in Ghana/Senegal.
    assert "nema" not in {c.agency_slug for c in _coverage_for("ghana")}
    assert "nema" not in {c.agency_slug for c in _coverage_for("senegal")}


def test_coverage_for_lgas_are_in_official_set():
    """Every LGA the seed assigns must come from the tenant's official set
    (services.lga_geo). The legacy LGA_POOL is now only a fallback (6e51d81)."""
    from services.lga_geo import all_lgas
    for tenant in ("kebbi", "ghana"):
        official = set(all_lgas(tenant))
        cov_lgas = {c.lga for c in _coverage_for(tenant)}
        assert cov_lgas <= official


def test_coverage_for_beneficiaries_non_negative():
    for c in _coverage_for("kebbi"):
        assert c.beneficiaries_served >= 0


def test_seed_source_constant_is_v1():
    assert SEED_SOURCE == "seed_v1"


# ─── Real-data rollup (build_stats, DB-free) ──────────────────────────────

LGAS = ["Argungu", "Bagudu", "Shanga"]
CENTRES = {"Argungu": (4.52, 12.74), "Bagudu": (3.93, 11.33), "Shanga": (4.58, 11.21)}


def _row(org, lga, buckets=("Health",), activity=None, source="iati_v1"):
    return ActivityRow(org_slug=org, org_name=org.upper(), lga=lga,
                       sectors=tuple(buckets), buckets=tuple(buckets),
                       activity=activity or f"{org}-{lga}", source=source)


def test_gaps_are_counted_against_every_lga_not_just_rows():
    """The seed view counted only LGAs that had rows, so coverage was 100%
    by construction. Every LGA of the tenant is in the denominator now."""
    s = build_stats("kebbi", LGAS, CENTRES, [_row("unicef", "Argungu")])
    assert s.total_lgas == 3 and s.covered_lgas == 1
    assert s.gap_lgas == ["Bagudu", "Shanga"]
    assert round(s.coverage_pct, 1) == 33.3


def test_overlap_needs_two_organisations_in_the_same_sector():
    different = build_stats("kebbi", LGAS, CENTRES, [
        _row("unicef", "Argungu", ("Water & sanitation",)),
        _row("eu", "Argungu", ("Social protection",)),
    ])
    same = build_stats("kebbi", LGAS, CENTRES, [
        _row("unicef", "Argungu", ("Health",)),
        _row("who", "Argungu", ("Health",)),
    ])
    assert different.duplication_pct == 0.0
    assert {p.lga: p.status for p in different.lga_points}["Argungu"] == "covered"
    assert {p.lga: p.status for p in same.lga_points}["Argungu"] == "duplicated"


def test_statewide_activity_is_its_own_column_not_an_lga():
    s = build_stats("kebbi", LGAS, CENTRES, [_row("eu", None), _row("unicef", "Shanga")])
    assert s.lga_columns[-1] == "Statewide"
    assert s.statewide_orgs == 1 and s.active_agencies == 2
    assert s.covered_lgas == 1                        # statewide covers no LGA
    assert [p.lga for p in s.lga_points] == LGAS      # no "Statewide" dot on the map
    eu = next(m for m in s.matrix if m.agency_slug == "eu")
    assert eu.row == [0, 0, 0, 1]


def test_country_tenants_say_countrywide():
    s = build_stats("ghana", ["Tamale"], {"Tamale": (-0.84, 9.4)}, [_row("wfp", None)])
    assert s.statewide_label == "Countrywide" and s.lga_columns == ["Tamale", "Countrywide"]


def test_rows_for_lgas_outside_the_tenant_are_ignored():
    s = build_stats("kebbi", LGAS, CENTRES, [_row("x", "Gusau")])
    assert s.active_agencies == 0 and s.covered_lgas == 0


def test_lga_points_sit_at_real_centres():
    s = build_stats("kebbi", LGAS, CENTRES, [])
    assert {p.lga: (p.lon, p.lat) for p in s.lga_points} == CENTRES


def test_beneficiaries_are_never_invented():
    s = build_stats("kebbi", LGAS, CENTRES, [_row("unicef", "Argungu")])
    assert all(a.beneficiaries_served is None for a in s.agencies)


def test_activities_are_counted_once_per_organisation():
    s = build_stats("kebbi", LGAS, CENTRES, [
        _row("unicef", "Argungu", activity="A1"), _row("unicef", "Shanga", activity="A1"),
        _row("unicef", None, activity="A2"),
    ])
    (u,) = s.agencies
    assert u.activities == 2 and u.statewide_activities == 1
    assert u.lgas_covered == ["Argungu", "Shanga"]


def test_iati_rows_carry_attribution():
    assert build_stats("kebbi", LGAS, CENTRES, [_row("unicef", "Argungu")]).attribution
    assert build_stats("kebbi", LGAS, CENTRES, []).attribution is None


def test_seed_fixtures_are_never_read():
    assert READ_EXCLUDES == "seed_v1"
    assert "<> :seed" in _REAL_COVERAGE.text
