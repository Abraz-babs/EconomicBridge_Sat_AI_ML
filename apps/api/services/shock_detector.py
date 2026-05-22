"""Flood + drought shock-event detectors (Slice 05).

Two detectors share the same statistical bones as the NDVI anomaly
detector in services/ndvi_anomaly.py — synthetic per-tenant time
series + linear-detrended z-score against a baseline window. The
specifics differ:

  FLOOD (Sentinel-1 SAR proxy):
    metric = surface backscatter in dB
    baseline = previous 60 days (rolling, detrended)
    a SUDDEN DROP (negative z, e.g. ≤ -2σ) over normally-dry
    pixels indicates open water has appeared (flood)
    projected onset: backscatter trend extrapolation puts the
    threshold-crossing ~24-48h ahead

  DROUGHT (MODIS LST + NDVI composite proxy):
    metric = composite stress index = LST_anomaly_C / 5 - NDVI_anomaly
    sustained positive index (heat up + vegetation down) over the
    recent 21 days triggers an alert
    severity scales with index magnitude

When the real Sentinel-1 GRD / MODIS LST ingestion lands, the same
detectors run against real raster time series and write rows with
source='sentinel1_v1' / 'modis_lst_v1'. The HTTP contract + table
shape are stable across the swap.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal


DETECTOR_NAME_FLOOD = "shock_flood_v1"
DETECTOR_NAME_DROUGHT = "shock_drought_v1"
DETECTOR_VERSION = "0.1.0-statistical"

# Common config
FLOOD_SERIES_DAYS: int = 60        # 2 months of daily SAR observations
FLOOD_BASELINE_DAYS: int = 40
FLOOD_RECENT_DAYS: int = 7
FLOOD_Z_THRESHOLD: float = 2.0

DROUGHT_SERIES_DAYS: int = 90
DROUGHT_BASELINE_DAYS: int = 60
DROUGHT_RECENT_DAYS: int = 21
DROUGHT_STRESS_THRESHOLD: float = 0.4

# Per-tenant seasonal priors. (mean_backscatter_dB, mean_lst_C, ndvi_mean,
# flood_risk_factor, drought_risk_factor) — risk factors scale the synthetic
# anomaly amplitude so dashboards show plausible variation per tenant.
TENANT_SHOCK_PROFILE: dict[str, tuple[float, float, float, float, float]] = {
    "kebbi":    (-10.5, 33.0, 0.45, 0.6, 1.0),   # arid → drought-prone
    "benue":    (-12.0, 28.0, 0.55, 1.0, 0.4),   # Benue river flood belt
    "plateau":  (-11.5, 25.0, 0.50, 0.5, 0.5),
    "kaduna":   (-11.0, 30.0, 0.48, 0.7, 0.7),
    "niger":    (-11.8, 31.0, 0.46, 0.8, 0.7),
    "zamfara":  (-10.0, 33.5, 0.43, 0.5, 1.1),
    "nasarawa": (-12.2, 29.0, 0.52, 0.7, 0.4),
    "fct":      (-11.7, 28.5, 0.50, 0.5, 0.4),
    "ghana":    (-12.5, 28.0, 0.58, 0.8, 0.3),
    "senegal":  (-12.0, 30.0, 0.52, 0.7, 0.6),
}

ShockEventType = Literal["flood", "drought"]
Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class FloodSeriesPoint:
    observed_at: date
    backscatter_db: float


@dataclass(frozen=True, slots=True)
class DroughtSeriesPoint:
    observed_at: date
    lst_anomaly_c: float
    ndvi_anomaly: float
    stress_index: float


@dataclass(frozen=True, slots=True)
class ShockDetection:
    event_type: ShockEventType
    detector_name: str
    detector_version: str
    severity: Severity
    confidence: float
    confidence_band: str          # HIGH/MEDIUM/LOW
    requires_human_review: bool
    projected_onset_hours: int
    affected_area_km2: float
    population_at_risk: int
    metrics: dict[str, float]
    flood_series: tuple[FloodSeriesPoint, ...] = field(default_factory=tuple)
    drought_series: tuple[DroughtSeriesPoint, ...] = field(default_factory=tuple)
    triggered: bool = False


# ─── Synthetic series ─────────────────────────────────────────────────────


def _hash_noise(tenant: str, day: date, kind: str) -> float:
    h = hashlib.md5(
        f"{tenant}|{day.isoformat()}|{kind}".encode(),
        usedforsecurity=False,
    ).digest()[:2]
    return ((int.from_bytes(h, "big") / 65535.0) - 0.5)


def synthetic_flood_series(
    tenant_id: str,
    *,
    end: date | None = None,
    inject_flood: bool = False,
) -> tuple[FloodSeriesPoint, ...]:
    """Daily SAR backscatter. Quiet years: mean -11 dB ± 0.6.
    Flood injection drops the last 7 days by ~5 dB (canonical water-over-land)."""
    profile = TENANT_SHOCK_PROFILE.get(tenant_id, (-11.5, 29, 0.50, 0.7, 0.7))
    mean_db = profile[0]
    flood_factor = profile[3]

    if end is None:
        end = date.today()
    samples: list[FloodSeriesPoint] = []
    for offset in range(FLOOD_SERIES_DAYS - 1, -1, -1):
        d = end - timedelta(days=offset)
        noise = _hash_noise(tenant_id, d, "sar") * 1.2
        db = mean_db + noise
        if inject_flood and offset < FLOOD_RECENT_DAYS:
            db -= 5.0 * flood_factor   # canonical water-over-land drop
        samples.append(FloodSeriesPoint(observed_at=d, backscatter_db=db))
    return tuple(samples)


def synthetic_drought_series(
    tenant_id: str,
    *,
    end: date | None = None,
    inject_drought: bool = False,
) -> tuple[DroughtSeriesPoint, ...]:
    """Daily composite stress index from synthetic MODIS LST + NDVI anomalies."""
    profile = TENANT_SHOCK_PROFILE.get(tenant_id, (-11.5, 29, 0.50, 0.7, 0.7))
    drought_factor = profile[4]

    if end is None:
        end = date.today()
    samples: list[DroughtSeriesPoint] = []
    for offset in range(DROUGHT_SERIES_DAYS - 1, -1, -1):
        d = end - timedelta(days=offset)
        lst_anom = _hash_noise(tenant_id, d, "lst") * 2.0
        ndvi_anom = _hash_noise(tenant_id, d, "ndvi") * 0.15
        if inject_drought and offset < DROUGHT_RECENT_DAYS:
            lst_anom += 4.0 * drought_factor   # sustained heat-up
            ndvi_anom -= 0.20 * drought_factor  # vegetation collapse
        stress = (lst_anom / 5.0) - ndvi_anom
        samples.append(DroughtSeriesPoint(
            observed_at=d,
            lst_anomaly_c=lst_anom,
            ndvi_anomaly=ndvi_anom,
            stress_index=stress,
        ))
    return tuple(samples)


# ─── Detectors ────────────────────────────────────────────────────────────


def detect_flood(
    tenant_id: str,
    *,
    series: tuple[FloodSeriesPoint, ...] | None = None,
    inject_flood: bool = False,
    recent_n: int | None = None,
    baseline_n: int | None = None,
) -> ShockDetection:
    """Linear-detrended z-score on SAR backscatter. NEGATIVE z = flood.

    `recent_n` / `baseline_n` override the window sizes (in points, not
    days). Defaults to FLOOD_RECENT_DAYS / FLOOD_BASELINE_DAYS for the
    daily synthetic series. Real Sentinel-1 GRD has a ~6-day repeat over
    a state-sized ROI, so the live caller passes smaller point counts
    (≈ recent_n=2, baseline_n=8 for 12-day recent / 48-day baseline).
    """
    if series is None:
        series = synthetic_flood_series(tenant_id, inject_flood=inject_flood)
    rwindow = recent_n if recent_n is not None else FLOOD_RECENT_DAYS
    bwindow = baseline_n if baseline_n is not None else FLOOD_BASELINE_DAYS
    if len(series) < bwindow + rwindow:
        raise ValueError(
            f"flood series too short: {len(series)} < {bwindow + rwindow}"
        )

    baseline = series[-(rwindow + bwindow): -rwindow]
    recent = series[-rwindow:]
    baseline_values = [p.backscatter_db for p in baseline]
    intercept, slope, residual_std = _linear_detrend_stats(baseline_values)
    expected_x = len(baseline_values) + rwindow / 2.0
    expected = intercept + slope * expected_x
    recent_mean = sum(p.backscatter_db for p in recent) / len(recent)
    bstd = max(residual_std, 1e-6)
    z = (recent_mean - expected) / bstd

    triggered = z <= -FLOOD_Z_THRESHOLD
    severity, band, confidence = _scale_from_z(z)
    profile = TENANT_SHOCK_PROFILE.get(tenant_id, (0, 0, 0, 0.7, 0.7))
    area_km2 = 25.0 * profile[3] * max(0.0, -z - FLOOD_Z_THRESHOLD + 1.0) if triggered else 0.0
    population = int(area_km2 * 220)   # ~220 people/km² rural avg
    onset_hours = 24 if triggered else max(0, int(48 * (1 - abs(z) / FLOOD_Z_THRESHOLD)))

    return ShockDetection(
        event_type="flood",
        detector_name=DETECTOR_NAME_FLOOD,
        detector_version=DETECTOR_VERSION,
        severity=severity,
        confidence=confidence,
        confidence_band=band,
        requires_human_review=not triggered or band != "HIGH",
        projected_onset_hours=onset_hours,
        affected_area_km2=area_km2,
        population_at_risk=population,
        metrics={
            "recent_mean_db": recent_mean,
            "baseline_mean_db": expected,
            "baseline_std_db": bstd,
            "z_score": z,
        },
        flood_series=series,
        triggered=triggered,
    )


def detect_drought(
    tenant_id: str,
    *,
    series: tuple[DroughtSeriesPoint, ...] | None = None,
    inject_drought: bool = False,
) -> ShockDetection:
    """Sustained positive composite stress index over the recent window."""
    if series is None:
        series = synthetic_drought_series(tenant_id, inject_drought=inject_drought)
    if len(series) < DROUGHT_BASELINE_DAYS + DROUGHT_RECENT_DAYS:
        raise ValueError(
            f"drought series too short: {len(series)} < "
            f"{DROUGHT_BASELINE_DAYS + DROUGHT_RECENT_DAYS}"
        )
    recent = series[-DROUGHT_RECENT_DAYS:]
    recent_stress = sum(p.stress_index for p in recent) / len(recent)
    # Severity scales with how far above threshold the stress is.
    triggered = recent_stress >= DROUGHT_STRESS_THRESHOLD
    pseudo_z = recent_stress / 0.20   # 1σ ≈ 0.20 in synthetic series
    severity, band, confidence = _scale_from_z(-pseudo_z if triggered else 0.0)
    if not triggered:
        severity = "low"
        band = "LOW"
        confidence = max(0.0, 1.0 - abs(pseudo_z))
    profile = TENANT_SHOCK_PROFILE.get(tenant_id, (0, 0, 0, 0.7, 0.7))
    area_km2 = 80.0 * profile[4] * max(0.0, pseudo_z) if triggered else 0.0
    population = int(area_km2 * 140)   # drought hits wider, less dense areas
    onset_hours = 36 if triggered else 72

    return ShockDetection(
        event_type="drought",
        detector_name=DETECTOR_NAME_DROUGHT,
        detector_version=DETECTOR_VERSION,
        severity=severity,
        confidence=confidence,
        confidence_band=band,
        requires_human_review=not triggered or band != "HIGH",
        projected_onset_hours=onset_hours,
        affected_area_km2=area_km2,
        population_at_risk=population,
        metrics={
            "recent_stress_mean": recent_stress,
            "stress_threshold": DROUGHT_STRESS_THRESHOLD,
            "pseudo_z": pseudo_z,
        },
        drought_series=series,
        triggered=triggered,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────


def _linear_detrend_stats(values: list[float]) -> tuple[float, float, float]:
    """OLS y = intercept + slope·i + residuals; return std of residuals."""
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), 0.0, 0.0
    xs = list(range(n))
    xbar = (n - 1) / 2.0
    ybar = sum(values) / n
    num = sum((xs[i] - xbar) * (values[i] - ybar) for i in range(n))
    den = sum((x - xbar) ** 2 for x in xs)
    slope = num / den if den > 0 else 0.0
    intercept = ybar - slope * xbar
    residuals = [values[i] - (intercept + slope * xs[i]) for i in range(n)]
    rmean = sum(residuals) / len(residuals)
    rvar = sum((r - rmean) ** 2 for r in residuals) / max(len(residuals) - 1, 1)
    return intercept, slope, math.sqrt(rvar)


def _scale_from_z(z: float) -> tuple[Severity, str, float]:
    """|z| → (severity, band, confidence). Mirrors the cropguard bands."""
    abs_z = abs(z)
    if abs_z >= 3.5:
        return "critical", "HIGH", min(0.99, 0.85 + (abs_z - 3.5) / 10)
    if abs_z >= 2.5:
        return "high", "HIGH", 0.85
    if abs_z >= 2.0:
        return "medium", "MEDIUM", 0.78
    if abs_z >= 1.0:
        return "low", "MEDIUM", 0.62
    return "low", "LOW", max(0.3, 0.5 - abs_z * 0.1)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_dt(d) -> datetime:
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time(0, 0, tzinfo=timezone.utc))
