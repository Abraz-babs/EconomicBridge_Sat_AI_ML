"""LGA boundaries — the data file is the product, so these tests audit the data.

Every detection that says "this happened in Jega" depends on this file drawing
Jega in the right place under the right name. The checks below are the same
ones the build refuses to ship without, re-run against what is committed.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from sources import lga_boundaries as lb

CENTROIDS = Path(__file__).resolve().parents[1] / "data" / "lga_centroids.json"


def _centroids() -> dict:
    return json.loads(CENTROIDS.read_text(encoding="utf-8"))


def test_boundaries_cover_exactly_the_lgas_the_platform_already_uses():
    """Same (tenant, lga) multiset as the centroids every other module reads."""
    want = Counter((t, g["lga"]) for t, rows in _centroids().items() for g in rows)
    have = Counter((b.tenant, b.lga) for t in lb.tenants() for b in lb.for_tenant(t))
    assert have == want


def test_every_stored_centroid_is_its_own_boundarys_centre_of_mass():
    """Key integrity: the centroid file and this file describe the same shapes.

    A naming or state-assignment mismatch would move a centroid far from the
    centre of the polygon filed under its name. 5e-4 deg is ~55 m; genuine
    matches differ only by 5-decimal rounding.
    """
    off = []
    for t, rows in _centroids().items():
        for g in rows:
            b = lb.get(t, g["lga"])
            cx, cy = lb.centroid(b.geometry)
            if abs(cx - g["lon"]) > 5e-4 or abs(cy - g["lat"]) > 5e-4:
                off.append((t, g["lga"], round(cx - g["lon"], 5), round(cy - g["lat"], 5)))
    assert not off, off[:5]


def test_concave_lgas_are_recorded_and_their_centres_really_are_outside():
    """Pins a live defect so it can neither be forgotten nor silently change.

    For a concave LGA the centre of mass lies outside the LGA, in a neighbour.
    Every centroid-sampled feed reads the neighbour there. Found 2026-09-15:
    Bungudu's centre sits in Gusau, Buruku's in Gboko.
    """
    concave = lb.concave_lgas()
    assert ("zamfara", "Bungudu") in concave
    assert ("benue", "Buruku") in concave
    cent = {(t, g["lga"]): (g["lon"], g["lat"]) for t, rows in _centroids().items() for g in rows}
    for tenant, lga in concave:
        lon, lat = cent[(tenant, lga)]
        assert not lb.get(tenant, lga).contains(lon, lat), (tenant, lga)
        neighbour = lb.lga_at(tenant, lon, lat)
        assert neighbour is None or neighbour.lga != lga
    # ...and every OTHER centroid is inside its own LGA.
    for (tenant, lga), (lon, lat) in cent.items():
        if (tenant, lga) not in concave:
            assert lb.get(tenant, lga).contains(lon, lat), (tenant, lga)


def test_the_centre_of_mass_of_a_crescent_lies_outside_it():
    """Why the concave list exists at all, shown on a toy U-shape."""
    u_shape = {"type": "Polygon", "coordinates": [[
        [0, 0], [10, 0], [10, 10], [8, 10], [8, 2], [2, 2], [2, 10], [0, 10], [0, 0],
    ]]}
    cx, cy = lb.centroid(u_shape)
    assert cx == pytest.approx(5.0)
    assert not lb.point_in_geometry(u_shape, cx, cy)


def test_centroid_subtracts_holes():
    ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    off_centre_hole = [[6, 6], [9, 6], [9, 9], [6, 9], [6, 6]]
    solid = lb.centroid({"type": "Polygon", "coordinates": [ring]})
    holed = lb.centroid({"type": "Polygon", "coordinates": [ring, off_centre_hole]})
    assert solid == pytest.approx((5.0, 5.0))
    assert holed[0] < 5.0 and holed[1] < 5.0, "mass moves away from the hole"


def test_a_point_is_attributed_to_the_lga_it_falls_in():
    jega = next(g for g in _centroids()["kebbi"] if g["lga"] == "Jega")
    hit = lb.lga_at("kebbi", jega["lon"], jega["lat"])
    assert hit is not None and hit.lga == "Jega"


def test_a_point_outside_every_pilot_is_attributed_to_nothing():
    assert lb.lga_at("kebbi", -20.0, 5.0) is None       # Atlantic
    assert lb.lga_at("atlantis", 4.43, 12.12) is None   # unknown tenant


def test_get_finds_one_lga_by_name():
    assert lb.get("kebbi", "Jega") is not None
    assert lb.get("kebbi", "Nowhere") is None


def test_point_in_geometry_respects_holes():
    square_with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
        ],
    }
    assert lb.point_in_geometry(square_with_hole, 2, 2)
    assert not lb.point_in_geometry(square_with_hole, 5, 5), "inside the hole"
    assert not lb.point_in_geometry(square_with_hole, 11, 5)


def test_a_multipolygon_matches_either_part():
    two_islands = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]],
        ],
    }
    assert lb.point_in_geometry(two_islands, 0.5, 0.5)
    assert lb.point_in_geometry(two_islands, 5.5, 5.5)
    assert not lb.point_in_geometry(two_islands, 3, 3)


def test_unsupported_geometry_is_refused_not_guessed():
    with pytest.raises(ValueError):
        lb.point_in_geometry({"type": "LineString", "coordinates": []}, 0, 0)


def test_attribution_is_recorded_for_every_source_country():
    """CC BY is only satisfied if we can say whose boundaries these are."""
    a = lb.attribution()
    assert {"NGA", "GHA", "SEN"} <= set(a)
    for iso, meta in a.items():
        assert "Creative Commons" in (meta.get("licence") or ""), iso
        assert meta.get("source"), iso


def test_a_missing_boundary_file_is_an_error_not_an_empty_scan(monkeypatch, tmp_path):
    """No boundaries must never read as "no LGAs to scan"."""
    real = lb.DATA_PATH
    monkeypatch.setattr(lb, "DATA_PATH", tmp_path / "missing.geojson")
    lb.clear_cache()
    try:
        with pytest.raises(lb.LgaBoundaryError):
            lb.tenants()
    finally:
        monkeypatch.setattr(lb, "DATA_PATH", real)
        lb.clear_cache()


def test_an_empty_boundary_file_is_an_error(monkeypatch, tmp_path):
    empty = tmp_path / "empty.geojson"
    empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    real = lb.DATA_PATH
    monkeypatch.setattr(lb, "DATA_PATH", empty)
    lb.clear_cache()
    try:
        with pytest.raises(lb.LgaBoundaryError):
            lb.for_tenant("kebbi")
    finally:
        monkeypatch.setattr(lb, "DATA_PATH", real)
        lb.clear_cache()
