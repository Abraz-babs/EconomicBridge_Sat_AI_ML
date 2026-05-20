"""Unit tests for processors/conflict_features.py.

Pure functions only — no DB, no network. These pin the feature-extraction
contract so future swaps (e.g. fancier clustering, NDVI from Sentinel-2)
don't accidentally change what the model sees.
"""
from __future__ import annotations

import math

from processors.conflict_features import (
    BRIGHTNESS_SATURATION_K,
    DEFAULT_BOUNDARY_DISTANCE_KM,
    GRID_CELL_DEG,
    HERDER_DENSITY_BY_RISK,
    NEW_GEOGRAPHY_RADIUS_KM,
    HeatDetection,
    build_cluster,
    cluster_detections,
    clusters_from_detections,
    haversine_km,
    herder_density_for,
    is_new_geography,
    normalise_brightness,
)


def _hd(lat: float, lon: float, *, b: float | None = 330.0, i: str | None = None) -> HeatDetection:
    return HeatDetection(
        detection_id=i or f"d-{lat:.3f}-{lon:.3f}",
        latitude=lat,
        longitude=lon,
        brightness_k=b,
    )


# ─── Brightness normalisation ──────────────────────────────────────────────


def test_normalise_brightness_caps_at_one_above_saturation():
    assert normalise_brightness(420.0) == 1.0


def test_normalise_brightness_handles_null_as_zero():
    assert normalise_brightness(None) == 0.0


def test_normalise_brightness_is_linear_in_range():
    half = BRIGHTNESS_SATURATION_K / 2
    assert math.isclose(normalise_brightness(half), 0.5, abs_tol=1e-9)


def test_normalise_brightness_rejects_nonpositive():
    assert normalise_brightness(0.0) == 0.0
    assert normalise_brightness(-50.0) == 0.0


# ─── Herder density mapping ────────────────────────────────────────────────


def test_herder_density_known_tiers():
    assert herder_density_for("critical") == HERDER_DENSITY_BY_RISK["critical"]
    assert herder_density_for("HIGH") == HERDER_DENSITY_BY_RISK["high"]
    assert herder_density_for("medium") == HERDER_DENSITY_BY_RISK["medium"]
    assert herder_density_for("low") == HERDER_DENSITY_BY_RISK["low"]


def test_herder_density_defaults_to_medium_for_unknown_or_null():
    assert herder_density_for(None) == HERDER_DENSITY_BY_RISK["medium"]
    assert herder_density_for("not-a-tier") == HERDER_DENSITY_BY_RISK["medium"]


# ─── Haversine ─────────────────────────────────────────────────────────────


def test_haversine_zero_distance():
    assert haversine_km(12.0, 4.5, 12.0, 4.5) == 0.0


def test_haversine_one_degree_lat_is_about_111km():
    # 1° latitude ≈ 111 km — universal regardless of longitude.
    assert math.isclose(haversine_km(0.0, 0.0, 1.0, 0.0), 111.0, abs_tol=1.0)


def test_haversine_kebbi_to_benue_capital_about_700km():
    # Birnin Kebbi (12.45, 4.20) → Makurdi (7.73, 8.50): ≈ 705 km
    d = haversine_km(12.45, 4.20, 7.73, 8.50)
    assert 650 < d < 750, d


# ─── is_new_geography ──────────────────────────────────────────────────────


def test_new_geography_when_no_prior_points():
    assert is_new_geography(12.0, 4.5, []) is True


def test_new_geography_false_when_prior_point_within_radius():
    # Same lat/lon as a prior alert -> definitely not new.
    assert is_new_geography(12.0, 4.5, [(12.0, 4.5)]) is False


def test_new_geography_respects_radius():
    # ~5 km offset -> not new
    nearby = (12.0 + 0.045, 4.5)  # ~5 km north
    assert is_new_geography(12.0, 4.5, [nearby]) is False
    # ~22 km offset -> outside radius -> new
    far = (12.0 + 0.20, 4.5)
    assert is_new_geography(12.0, 4.5, [far]) is True
    # double-check the constant we depend on
    assert NEW_GEOGRAPHY_RADIUS_KM == 20.0


# ─── Clustering ────────────────────────────────────────────────────────────


def test_cluster_detections_empty():
    assert cluster_detections([]) == []


def test_cluster_detections_groups_same_cell():
    a = _hd(12.05, 4.55, i="a")
    b = _hd(12.07, 4.58, i="b")
    c = _hd(12.95, 4.55, i="c")  # different lat cell
    out = cluster_detections([a, b, c])
    assert len(out) == 2
    members_by_size = sorted([len(m) for _, _, m in out], reverse=True)
    assert members_by_size == [2, 1]


def test_cluster_detections_respects_grid_constant():
    # Two detections separated by clearly more than one cell fall in
    # different cells. We avoid testing the at-boundary case because
    # IEEE-754 makes floor(value / 0.1) ambiguous when value is an exact
    # multiple of 0.1 (e.g. 12.0 + 0.1 = 12.10000000001).
    a = _hd(12.0, 4.5, i="a")
    b = _hd(12.0 + 2 * GRID_CELL_DEG, 4.5, i="b")
    out = cluster_detections([a, b])
    assert len(out) == 2


# ─── build_cluster ────────────────────────────────────────────────────────


def test_build_cluster_uses_centroid_and_max_brightness():
    members = [_hd(12.0, 4.5, b=320.0), _hd(12.04, 4.54, b=380.0)]
    cluster = build_cluster(
        tenant_id="kebbi",
        lat_bucket=120,
        lon_bucket=45,
        members=members,
        tenant_conflict_risk="critical",
        historical_incident_count=4,
        prior_alert_points=[],
    )
    assert math.isclose(cluster.centroid_lat, 12.02, abs_tol=1e-6)
    assert math.isclose(cluster.centroid_lon, 4.52, abs_tol=1e-6)
    assert cluster.max_brightness_k == 380.0
    assert cluster.detection_count == 2
    assert cluster.heat_signature_intensity == normalise_brightness(380.0)
    assert cluster.herder_density == HERDER_DENSITY_BY_RISK["critical"]
    assert cluster.historical_incidents == 4
    assert cluster.boundary_distance_km == DEFAULT_BOUNDARY_DISTANCE_KM
    assert cluster.ndvi_delta == 0.0
    assert cluster.rainfall_anomaly == 0.0
    assert cluster.is_new_geography is True


def test_build_cluster_marks_not_new_when_prior_alert_close():
    members = [_hd(12.0, 4.5)]
    cluster = build_cluster(
        tenant_id="kebbi",
        lat_bucket=120, lon_bucket=45,
        members=members,
        tenant_conflict_risk="critical",
        historical_incident_count=0,
        prior_alert_points=[(12.01, 4.51)],  # ~1.5 km away
    )
    assert cluster.is_new_geography is False


def test_build_cluster_id_is_stable():
    members = [_hd(12.0, 4.5)]
    args = dict(
        tenant_id="kebbi",
        lat_bucket=120, lon_bucket=45,
        members=members,
        tenant_conflict_risk="critical",
        historical_incident_count=0,
        prior_alert_points=[],
    )
    a = build_cluster(**args)
    b = build_cluster(**args)
    assert a.cluster_id == b.cluster_id


def test_build_cluster_max_brightness_handles_null_members():
    members = [_hd(12.0, 4.5, b=None), _hd(12.01, 4.51, b=None)]
    cluster = build_cluster(
        tenant_id="kebbi",
        lat_bucket=120, lon_bucket=45,
        members=members,
        tenant_conflict_risk="critical",
        historical_incident_count=0,
        prior_alert_points=[],
    )
    assert cluster.max_brightness_k is None
    assert cluster.heat_signature_intensity == 0.0


# ─── clusters_from_detections (high-level) ────────────────────────────────


def test_clusters_from_detections_end_to_end():
    detections = [
        _hd(12.0, 4.5, b=320.0, i="d1"),
        _hd(12.03, 4.52, b=350.0, i="d2"),
        _hd(12.95, 5.10, b=330.0, i="d3"),  # different cell
    ]
    clusters = clusters_from_detections(
        tenant_id="kebbi",
        detections=detections,
        tenant_conflict_risk="critical",
        historical_incident_count=2,
        prior_alert_points=[(12.99, 5.05)],   # close to cluster 2 only
    )
    assert len(clusters) == 2
    by_count = sorted([c.detection_count for c in clusters], reverse=True)
    assert by_count == [2, 1]
    # The cluster near the prior alert point is NOT new geography.
    near_prior = [c for c in clusters if c.detection_count == 1][0]
    assert near_prior.is_new_geography is False
    # The other one is new.
    far = [c for c in clusters if c.detection_count == 2][0]
    assert far.is_new_geography is True
