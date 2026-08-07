"""Coordinate → administrative unit.

The values asserted here are real places checked against the 447-unit
geoBoundaries dataset, not fixtures — if a future dataset rebuild moves a
centroid enough to break one of these, that is worth knowing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from services.lga_geo import MAX_PLAUSIBLE_KM, haversine_km, nearest_unit

client = TestClient(app)
ENDPOINT = "/api/v1/geo/resolve"


# ─── the distance primitive ──────────────────────────────────────────────

def test_haversine_is_zero_for_a_point_against_itself():
    assert haversine_km(4.2, 12.45, 4.2, 12.45) == pytest.approx(0.0, abs=1e-9)


def test_haversine_matches_an_independently_derived_separation():
    """Birnin Kebbi → Abuja.

    The expected value is NOT taken from our own function — that would only
    prove it agrees with itself. It comes from a planar cross-check computed
    separately: dx = Δlon · 111.320 · cos(mid-lat), dy = Δlat · 110.574,
    hypotenuse ≈ 520.6 km. Haversine should sit a shade above that over this
    distance, and does (≈521.8).
    """
    d = haversine_km(4.1975, 12.4539, 7.4951, 9.0579)

    assert d == pytest.approx(520.6, rel=0.01)


def test_haversine_is_symmetric():
    a = haversine_km(4.2, 12.45, -0.187, 5.6037)
    b = haversine_km(-0.187, 5.6037, 4.2, 12.45)

    assert a == pytest.approx(b)


# ─── the lookup ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "place,lon,lat,tenant",
    [
        ("Birnin Kebbi", 4.1975, 12.4539, "kebbi"),
        ("Abuja",        7.4951,  9.0579, "fct"),
        ("Accra",       -0.1870,  5.6037, "ghana"),
        ("Dakar",      -17.4467, 14.7167, "senegal"),
    ],
)
def test_known_cities_resolve_to_the_right_pilot(place, lon, lat, tenant):
    hit = nearest_unit(lon, lat)

    assert hit is not None, place
    assert hit[0] == tenant, f"{place} landed in {hit[0]}"


@pytest.mark.parametrize(
    "place,lon,lat",
    [
        ("Lagos — a real city, but not one of our pilots", 3.3792, 6.5244),
        ("London — nonsense input", -0.1276, 51.5072),
        ("Null Island — the classic coordinate bug", 0.0, 0.0),
    ],
)
def test_points_outside_coverage_name_nothing(place, lon, lat):
    """A confidently wrong LGA is worse than no LGA. Lagos is the case that
    matters: close enough to be plausible, still not ours."""
    assert nearest_unit(lon, lat) is None, place


def test_the_returned_distance_is_the_distance_to_that_unit():
    from services.lga_geo import LGA_CENTROIDS

    lon, lat = 4.1975, 12.4539
    tenant, lga, dist = nearest_unit(lon, lat)
    ulon, ulat = LGA_CENTROIDS[tenant][lga]

    assert dist == pytest.approx(haversine_km(lon, lat, ulon, ulat))


def test_no_unit_is_ever_returned_beyond_the_plausibility_bound():
    hit = nearest_unit(14.0, 12.0)  # eastern Chad — far from every pilot

    assert hit is None or hit[2] <= MAX_PLAUSIBLE_KM


# ─── the endpoint ────────────────────────────────────────────────────────

def test_endpoint_returns_the_platform_spelling():
    r = client.get(ENDPOINT, params={"lon": 4.1975, "lat": 12.4539})

    assert r.status_code == 200
    d = r.json()["data"]
    assert d["tenant_id"] == "kebbi"
    assert d["lga"] == "Birnin Kebbi"
    assert d["distance_km"] < 20


def test_endpoint_answers_nulls_not_404_when_outside_coverage():
    """A coordinate someone just mistyped is a normal answer, not an error."""
    r = client.get(ENDPOINT, params={"lon": 3.3792, "lat": 6.5244})

    assert r.status_code == 200
    assert r.json()["data"] == {"tenant_id": None, "lga": None, "distance_km": None}


@pytest.mark.parametrize("params", [
    {"lon": 200, "lat": 10},      # longitude off the globe
    {"lon": 4.2, "lat": 91},      # latitude off the globe
    {"lon": 4.2},                 # latitude missing
])
def test_impossible_coordinates_are_rejected(params):
    assert client.get(ENDPOINT, params=params).status_code == 422


def test_endpoint_needs_no_authentication():
    """Open administrative geography, no tenant data — and the Farm Check bulk
    path calls it per row, so it must not require a session."""
    r = client.get(ENDPOINT, params={"lon": -0.187, "lat": 5.6037})

    assert r.status_code == 200
    assert r.json()["data"]["tenant_id"] == "ghana"
