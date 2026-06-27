"""On-demand single-farm vegetation check (CropGuard "Farm Check").

Given a coordinate and a crop type, query Copernicus Sentinel-2 NDVI and
Sentinel-1 SAR over a small box around that point and return a crop-aware
vegetation-health verdict — the field-level complement to the state/LGA
monitoring, which stays unchanged.

Honest about resolution: Sentinel-2 is ~10 m/pixel, so one farm is a small
cluster of pixels — good for a few-hectare plot, coarse for a tiny one.
Higher-resolution imagery (e.g. NASRDA NigeriaSat / NCRS) would sharpen this
to sub-field. The reading is the latest cloud-free optical pass in the window;
SAR is all-weather and fills in when clouds block the optical view.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sources.sentinel_statistical import (
    EVALSCRIPT_S1_VV_DB,
    EVALSCRIPT_S2_NDVI_CLOUDMASKED,
    SentinelStatisticalClient,
    StatPoint,
)

log = logging.getLogger(__name__)

SOURCE = "copernicus_sentinel_v1"

# Farm-scale aggregation grid: ~0.0001° ≈ 11 m, matching Sentinel-2's native
# 10 m. (State-scale ingest uses ~1.4 km — far too coarse for one farm.)
FARM_RESOLUTION_DEG = 0.0001
DEFAULT_HALF_M = 120          # half box side → ~240 m box ≈ 5.8 ha
NDVI_WINDOW_DAYS = 60         # look back this far for usable optical passes
SAR_WINDOW_DAYS = 30
# A pass is "usable" if its cloud-free pixel count is at least this fraction of
# the clearest pass in the window — lets us take the LATEST usable pass rather
# than the latest fully-clear one (clouds are masked per pixel via SCL).
MIN_CLEAR_FRACTION = 0.25
TREND_POINTS = 8

# Indicative PEAK-season healthy NDVI per crop (real value depends on growth
# stage). Used only to phrase a crop-aware verdict — NDVI itself is the
# measurement. Sources: typical canopy NDVI ranges for these crops.
CROP_NDVI_PEAK: dict[str, float] = {
    "maize": 0.72, "rice": 0.72, "cassava": 0.74, "sorghum": 0.62,
    "millet": 0.58, "yam": 0.70, "cowpea": 0.62, "groundnut": 0.62,
    "soybean": 0.70, "wheat": 0.66, "tomato": 0.62, "pepper": 0.60,
    "vegetables": 0.62, "sugarcane": 0.78, "oil palm": 0.80, "cocoa": 0.82,
    "plantain": 0.80, "banana": 0.80, "cotton": 0.66, "sesame": 0.60,
    "onion": 0.58, "wheat ": 0.66,
}
DEFAULT_PEAK = 0.70
# Common synonyms → canonical crop key.
_CROP_SYNONYMS = {"corn": "maize", "maize ": "maize", "soya": "soybean",
                  "soya bean": "soybean", "guinea corn": "sorghum",
                  "irish potato": "vegetables", "potato": "vegetables"}


@dataclass(frozen=True, slots=True)
class FarmCheckResult:
    lat: float
    lon: float
    crop: str
    ndvi: float | None
    ndvi_date: str | None
    health: str               # healthy|moderate|stressed|poor|bare|unknown
    verdict: str
    sar_db: float | None
    sar_date: str | None
    trend: list[dict] = field(default_factory=list)   # [{date, ndvi}]
    sample_count: int = 0
    area_ha: float = 0.0
    resolution_m: int = 11
    source: str = SOURCE
    note: str = ""


def normalise_crop(crop: str | None) -> str:
    c = (crop or "").strip().lower()
    return _CROP_SYNONYMS.get(c, c)


def classify_health(ndvi: float | None, crop: str) -> tuple[str, str]:
    """Crop-aware vegetation-health verdict from an NDVI value."""
    label = crop or "the crop"
    if ndvi is None:
        return "unknown", ("No cloud-free optical reading in the window — "
                           "try a wider date range, or rely on the SAR signal.")
    if ndvi < 0.15:
        return "bare", "Bare soil / no active vegetation detected at this point."
    peak = CROP_NDVI_PEAK.get(normalise_crop(crop), DEFAULT_PEAK)
    ratio = ndvi / peak
    if ratio >= 0.85:
        return "healthy", f"Healthy, vigorous canopy — strong for {label}."
    if ratio >= 0.65:
        return "moderate", f"Moderate vigour — developing or mildly stressed {label}."
    if ratio >= 0.45:
        return "stressed", f"Stressed / sparse canopy — {label} below its healthy range."
    return "poor", (f"Poor — very sparse or senesced; check whether {label} "
                    "is established here.")


def latest_usable_pass(
    points: list[StatPoint], min_fraction: float = MIN_CLEAR_FRACTION,
) -> StatPoint | None:
    """The MOST RECENT pass whose clear-pixel count is >= `min_fraction` of the
    clearest pass — so the headline uses the freshest imagery that still has
    enough cloud-free ground to trust, not the latest fully-clear pass.
    """
    valid = [p for p in points if p.mean is not None and p.sample_count > 0]
    if not valid:
        return None
    max_count = max(p.sample_count for p in valid)
    acceptable = [p for p in valid if p.sample_count >= min_fraction * max_count]
    return acceptable[-1] if acceptable else valid[-1]


def bbox_around(lat: float, lon: float, half_m: float) -> tuple[float, float, float, float]:
    """A (W, S, E, N) WGS84 box of side 2*half_m metres centred on the point."""
    dlat = half_m / 111_320.0
    dlon = half_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


async def check_farm(
    client: SentinelStatisticalClient,
    *,
    lat: float,
    lon: float,
    crop: str,
    half_m: float = DEFAULT_HALF_M,
) -> FarmCheckResult:
    """Query Sentinel-2 NDVI + Sentinel-1 SAR for one farm and grade it."""
    bbox = bbox_around(lat, lon, half_m)
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    ndvi_points = await client.compute_time_series(
        bbox=bbox, start=end - timedelta(days=NDVI_WINDOW_DAYS), end=end,
        dataset="sentinel-2-l2a", evalscript=EVALSCRIPT_S2_NDVI_CLOUDMASKED,
        max_cloud_cover_pct=None,  # per-pixel SCL masking replaces scene filtering
        resolution_deg=FARM_RESOLUTION_DEG,
    )
    valid_ndvi = [p for p in ndvi_points if p.mean is not None and p.sample_count > 0]
    latest = latest_usable_pass(valid_ndvi)
    max_clear = max((p.sample_count for p in valid_ndvi), default=0)
    cloud_affected = bool(latest and max_clear and latest.sample_count < 0.7 * max_clear)

    sar_points = await client.compute_time_series(
        bbox=bbox, start=end - timedelta(days=SAR_WINDOW_DAYS), end=end,
        dataset="sentinel-1-grd", evalscript=EVALSCRIPT_S1_VV_DB,
        resolution_deg=FARM_RESOLUTION_DEG,
    )
    valid_sar = [p for p in sar_points if p.mean is not None]
    latest_sar = valid_sar[-1] if valid_sar else None

    ndvi_val = round(latest.mean, 3) if latest else None
    health, verdict = classify_health(ndvi_val, crop)
    trend = [
        {"date": p.interval_from.date().isoformat(), "ndvi": round(p.mean, 3)}
        for p in valid_ndvi[-TREND_POINTS:]
    ]
    side_m = 2 * half_m
    return FarmCheckResult(
        lat=lat, lon=lon, crop=crop,
        ndvi=ndvi_val,
        ndvi_date=latest.interval_from.date().isoformat() if latest else None,
        health=health, verdict=verdict,
        sar_db=round(latest_sar.mean, 2) if latest_sar else None,
        sar_date=latest_sar.interval_from.date().isoformat() if latest_sar else None,
        trend=trend,
        sample_count=latest.sample_count if latest else 0,
        area_ha=round((side_m * side_m) / 10_000.0, 2),
        note=("Sentinel-2 (~10 m) NDVI from the latest usable pass "
              "(clouds masked per-pixel)"
              + (" — this pass was partly cloud-affected" if cloud_affected else "")
              + "; SAR is all-weather and typically more recent. One farm is a "
              "small pixel cluster at this resolution — NASRDA higher-resolution "
              "imagery would sharpen it to sub-field."),
    )
