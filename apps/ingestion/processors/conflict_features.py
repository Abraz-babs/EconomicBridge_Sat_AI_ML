"""Build conflict-predictor input vectors from real satellite signals.

The ML service's RF model expects seven features (see
apps/ml/models/conflict_predictor.py FEATURE_NAMES). This module turns
what the ingestion pipeline can actually observe today — clusters of
FIRMS heat detections + tenant config + recent alert history — into
those seven feature values.

A few features are **partially imputed** for v1 because the underlying
signals aren't online yet:

  | Feature                  | v1 source                                |
  |--------------------------|------------------------------------------|
  | heat_signature_intensity | real (cluster max brightness / 400 K)    |
  | boundary_distance_km     | imputed (constant 5 km until LGA polygons land) |
  | ndvi_delta               | imputed 0.0 (waiting on Sentinel-2 NDVI processing) |
  | herder_density           | real-ish (mapped from tenants.yaml conflict_risk) |
  | historical_incidents     | real (alert_events count, last 365 days) |
  | rainfall_anomaly         | imputed 0.0 (waiting on weather feed)    |
  | is_new_geography         | real (no prior conflict alert within ~20 km) |

The pipeline emits `model_version='1.0.0-feat-partial'` so downstream
consumers (audit log, dashboard) know which features were imputed.

Clustering uses a 0.1° grid (~11 km cells at the equator). Coarse but
appropriate when we have no LGA polygons yet — finer clustering would
just produce singleton clusters from sparse VIIRS pixels and inflate
the alert volume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

# ─── Constants ─────────────────────────────────────────────────────────────

# Grid cell size for clustering. ~11 km at the equator, narrows toward the
# poles. West African pilot tenants are between ~4° and ~16° N — close
# enough to equator that the variance is negligible.
GRID_CELL_DEG: float = 0.1

# Brightness saturation point used to normalise heat_signature_intensity.
# VIIRS bright_ti4 max is ~400 K; MODIS brightness ditto.
BRIGHTNESS_SATURATION_K: float = 400.0

# "Conflict risk" labels in tenants.yaml -> herder_density estimate.
# Calibrated against the relative risk Citadel reports for each tier.
HERDER_DENSITY_BY_RISK: dict[str, float] = {
    "critical": 0.85,
    "high":     0.65,
    "medium":   0.40,
    "low":      0.20,
}

# Anything within this radius of a prior conflict alert is NOT "new
# geography". Tunable; 20 km is roughly an LGA half-width in the pilot
# states.
NEW_GEOGRAPHY_RADIUS_KM: float = 20.0

# Placeholder boundary distance until LGA polygons land.
# 5 km matches the order-of-magnitude that herder-corridor analyses use
# for "adjacent to farmland" in this region.
DEFAULT_BOUNDARY_DISTANCE_KM: float = 5.0

# Model version label callers should attach to the prediction so the
# audit trail records which feature-imputation regime ran.
MODEL_VERSION_LABEL: str = "1.0.0-feat-partial"


# ─── Dataclasses ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HeatDetection:
    """Minimal projection of a heat_signatures row used for clustering."""

    detection_id: str
    latitude: float
    longitude: float
    brightness_k: float | None  # may be NULL on legacy rows


@dataclass(frozen=True, slots=True)
class DetectionCluster:
    """A spatial cluster of heat detections + its centroid + the inputs the
    predictor will see."""

    cluster_id: str          # stable id: "{tenant}-{lat_bucket}-{lon_bucket}"
    detection_ids: list[str]
    centroid_lat: float
    centroid_lon: float
    max_brightness_k: float | None
    detection_count: int
    # Derived features (precomputed once + reused for hashing/dedup).
    heat_signature_intensity: float
    boundary_distance_km: float
    ndvi_delta: float
    herder_density: float
    historical_incidents: int
    rainfall_anomaly: float
    is_new_geography: bool


# ─── Clustering ────────────────────────────────────────────────────────────


def _bucket(value: float, cell: float = GRID_CELL_DEG) -> int:
    return int(math.floor(value / cell))


def cluster_detections(
    detections: Iterable[HeatDetection],
    *,
    cell_size_deg: float = GRID_CELL_DEG,
) -> list[tuple[int, int, list[HeatDetection]]]:
    """Group detections by lat/lon grid cell.

    Returns a list of (lat_bucket, lon_bucket, members). Empty list when
    given no detections.
    """
    buckets: dict[tuple[int, int], list[HeatDetection]] = {}
    for d in detections:
        key = (_bucket(d.latitude, cell_size_deg), _bucket(d.longitude, cell_size_deg))
        buckets.setdefault(key, []).append(d)
    return [(la, lo, members) for (la, lo), members in buckets.items()]


# ─── Feature derivation ────────────────────────────────────────────────────


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def normalise_brightness(max_k: float | None) -> float:
    """Map a peak brightness (K) to [0, 1]. NULL maps to 0.0 (treated as
    no thermal signal — the conflict model will weight other features)."""
    if max_k is None or max_k <= 0:
        return 0.0
    return min(1.0, max_k / BRIGHTNESS_SATURATION_K)


def herder_density_for(conflict_risk: str | None) -> float:
    """Look up the tenant's conflict_risk → herder_density estimate."""
    if conflict_risk is None:
        return HERDER_DENSITY_BY_RISK["medium"]
    return HERDER_DENSITY_BY_RISK.get(conflict_risk.lower(), HERDER_DENSITY_BY_RISK["medium"])


def is_new_geography(
    centroid_lat: float,
    centroid_lon: float,
    prior_alert_points: Iterable[tuple[float, float]],
    *,
    radius_km: float = NEW_GEOGRAPHY_RADIUS_KM,
) -> bool:
    """True if no prior conflict alert sits within `radius_km` of the centroid."""
    for la, lo in prior_alert_points:
        if haversine_km(centroid_lat, centroid_lon, la, lo) <= radius_km:
            return False
    return True


def build_cluster(
    *,
    tenant_id: str,
    lat_bucket: int,
    lon_bucket: int,
    members: list[HeatDetection],
    tenant_conflict_risk: str | None,
    historical_incident_count: int,
    prior_alert_points: list[tuple[float, float]],
) -> DetectionCluster:
    """Turn one grid cell of detections into a DetectionCluster + features."""
    if not members:
        raise ValueError("cannot build cluster from empty members list")

    # Centroid = simple mean of member coords (cells are small enough that
    # planar mean ≈ great-circle mean).
    centroid_lat = sum(m.latitude for m in members) / len(members)
    centroid_lon = sum(m.longitude for m in members) / len(members)
    bright_values = [m.brightness_k for m in members if m.brightness_k is not None]
    max_bright = max(bright_values) if bright_values else None

    cluster_id = f"{tenant_id}-{lat_bucket:+05d}-{lon_bucket:+05d}"

    return DetectionCluster(
        cluster_id=cluster_id,
        detection_ids=[m.detection_id for m in members],
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        max_brightness_k=max_bright,
        detection_count=len(members),
        heat_signature_intensity=normalise_brightness(max_bright),
        boundary_distance_km=DEFAULT_BOUNDARY_DISTANCE_KM,
        ndvi_delta=0.0,
        herder_density=herder_density_for(tenant_conflict_risk),
        historical_incidents=historical_incident_count,
        rainfall_anomaly=0.0,
        is_new_geography=is_new_geography(
            centroid_lat, centroid_lon, prior_alert_points
        ),
    )


def clusters_from_detections(
    *,
    tenant_id: str,
    detections: Iterable[HeatDetection],
    tenant_conflict_risk: str | None,
    historical_incident_count: int,
    prior_alert_points: list[tuple[float, float]],
) -> list[DetectionCluster]:
    """High-level: cluster + derive features in one call."""
    out: list[DetectionCluster] = []
    for la, lo, members in cluster_detections(detections):
        out.append(
            build_cluster(
                tenant_id=tenant_id,
                lat_bucket=la,
                lon_bucket=lo,
                members=members,
                tenant_conflict_risk=tenant_conflict_risk,
                historical_incident_count=historical_incident_count,
                prior_alert_points=prior_alert_points,
            )
        )
    return out
