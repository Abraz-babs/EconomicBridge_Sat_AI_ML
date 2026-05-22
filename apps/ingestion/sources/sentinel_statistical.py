"""Sentinel Hub Statistical API client — server-side raster aggregation.

The Statistical API takes an evalscript + bbox + date range and returns a
JSON time series of per-day statistics (mean/min/max/stDev/histogram) over
the area. Lets us run ShockGuard (flood backscatter z-score) and
CropGuard NDVI anomaly detection on real Sentinel-1 + Sentinel-2 data
without ever opening a raster on our side — Sentinel Hub computes it
and we consume the JSON.

This client reuses CopernicusClient's OAuth token cache so we don't
double the token-refresh load. Same identity endpoint, same bearer
token, different POST target (.../api/v1/statistics).

Two canonical evalscripts ship with the module:
  EVALSCRIPT_S1_VV_DB — Sentinel-1 GRD VV polarisation in decibels
                        (10 · log10(linear)). Drives the flood detector.
  EVALSCRIPT_S2_NDVI  — Sentinel-2 L2A NDVI = (B08 - B04) / (B08 + B04).
                        Drives the drought + NDVI anomaly detectors.

The API uses Processing Units (PU). Each request over our pilot ROIs
(state-sized, daily aggregation, 60-day window) costs ~3-6 PU. CDSE's
free tier gives us 30000 PU/month, so we have headroom — but DON'T call
this from the request hot path. Schedule the ingest task instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from sources.copernicus import CopernicusClient, CopernicusError

log = logging.getLogger(__name__)


# ─── Canonical evalscripts ────────────────────────────────────────────────


EVALSCRIPT_S1_VV_DB: str = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VV", "dataMask"] }],
    output: [
      { id: "default", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default: [10 * Math.log10(Math.max(s.VV, 1e-6))],
    dataMask: [s.dataMask]
  };
}
"""

EVALSCRIPT_S2_NDVI: str = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "dataMask"] }],
    output: [
      { id: "default", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let denom = s.B08 + s.B04;
  let ndvi = denom > 0 ? (s.B08 - s.B04) / denom : 0;
  return {
    default: [ndvi],
    dataMask: [s.dataMask]
  };
}
"""


# ─── Dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StatPoint:
    """One aggregation interval's worth of statistics."""

    interval_from: datetime         # UTC, inclusive
    interval_to: datetime           # UTC, exclusive
    dataset: str                    # "sentinel-1-grd" or "sentinel-2-l2a"
    band_name: str                  # "default" for our evalscripts
    mean: float | None              # None when the interval was fully masked
    min_value: float | None
    max_value: float | None
    std_dev: float | None
    sample_count: int               # how many valid pixels contributed


# ─── Client ───────────────────────────────────────────────────────────────


class SentinelStatisticalClient:
    """Async wrapper around the CDSE Statistical API at
    sh.dataspace.copernicus.eu/api/v1/statistics. Reuses the
    CopernicusClient's OAuth + HTTP pool.
    """

    def __init__(self, copernicus: CopernicusClient) -> None:
        self._copernicus = copernicus
        self._settings = copernicus._settings  # noqa: SLF001 — same module family

    @property
    def configured(self) -> bool:
        return self._copernicus.configured

    async def compute_time_series(
        self,
        *,
        bbox: tuple[float, float, float, float],
        start: datetime,
        end: datetime,
        dataset: str,
        evalscript: str,
        agg_interval: str = "P1D",
        max_cloud_cover_pct: float | None = None,
    ) -> list[StatPoint]:
        """POST a Statistical API request and parse the response.

        Args:
            bbox: (W, S, E, N) WGS84 degrees.
            start, end: UTC bounding the analysis window.
            dataset: "sentinel-1-grd" or "sentinel-2-l2a".
            evalscript: JavaScript that computes the band(s) to aggregate.
                Use the EVALSCRIPT_S1_VV_DB / EVALSCRIPT_S2_NDVI constants.
            agg_interval: ISO 8601 duration. P1D = daily; P5D = 5-day.
            max_cloud_cover_pct: for Sentinel-2, drop scenes with cloud
                cover above this before aggregation. Ignored for SAR.

        Returns:
            List of StatPoint sorted interval_from ASC. Empty when the
            window has no usable acquisitions.
        """
        if not self.configured:
            log.debug("statistical: no Copernicus creds — empty result")
            return []
        if start >= end:
            raise ValueError("start must be earlier than end")

        token = await self._copernicus.access_token()
        body = _build_request_body(
            bbox=bbox, start=start, end=end, dataset=dataset,
            evalscript=evalscript, agg_interval=agg_interval,
            max_cloud_cover_pct=max_cloud_cover_pct,
        )

        async with self._http_ctx() as client:
            resp = await client.post(
                self._settings.copernicus_statistical_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=60.0,   # Statistical API is heavier than catalog
            )
        if resp.status_code != 200:
            raise CopernicusError(
                f"CDSE Statistical {resp.status_code}: {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise CopernicusError(
                f"CDSE Statistical: non-JSON body: {resp.text[:300]}"
            ) from exc

        return _parse_response(payload, dataset=dataset)

    def _http_ctx(self):
        # Borrow the CopernicusClient's HTTP context if it has one injected
        # (tests pin their own); otherwise spin up a fresh client.
        if self._copernicus._http is not None:  # noqa: SLF001
            from sources.copernicus import _Borrowed
            return _Borrowed(self._copernicus._http)  # noqa: SLF001
        return httpx.AsyncClient()


# ─── Request / response shaping ──────────────────────────────────────────


def _build_request_body(
    *,
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    dataset: str,
    evalscript: str,
    agg_interval: str,
    max_cloud_cover_pct: float | None,
) -> dict[str, Any]:
    """Shape one Statistical API request payload."""
    data_filter: dict[str, Any] = {}
    if dataset == "sentinel-1-grd":
        # SAR-specific: pin VV/VH polarisation + GRD acquisition mode so
        # the API doesn't accidentally mix Strip-Map + IW.
        data_filter["acquisitionMode"] = "IW"
        data_filter["polarization"] = "DV"
        data_filter["resolution"] = "HIGH"
    elif dataset == "sentinel-2-l2a" and max_cloud_cover_pct is not None:
        data_filter["maxCloudCoverage"] = max_cloud_cover_pct

    return {
        "input": {
            "bounds": {
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326",
                },
            },
            "data": [
                {
                    "type": dataset,
                    "dataFilter": data_filter,
                },
            ],
        },
        "aggregation": {
            "timeRange": {
                "from": _to_iso_utc(start),
                "to": _to_iso_utc(end),
            },
            "aggregationInterval": {"of": agg_interval},
            "evalscript": evalscript,
        },
        "calculations": {
            "default": {
                "statistics": {
                    "default": {"percentiles": {"k": [50]}},
                },
            },
        },
    }


def _parse_response(payload: Any, *, dataset: str) -> list[StatPoint]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data") or []
    points: list[StatPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        interval = row.get("interval") or {}
        outputs = row.get("outputs") or {}
        for band_name, output in outputs.items():
            bands = (output or {}).get("bands") or {}
            for sub_band, sub_value in bands.items():
                stats = (sub_value or {}).get("stats") or {}
                point = _make_point(
                    interval=interval,
                    dataset=dataset,
                    band_name=f"{band_name}:{sub_band}" if sub_band != "B0" else band_name,
                    stats=stats,
                )
                if point is not None:
                    points.append(point)
    points.sort(key=lambda p: p.interval_from)
    return points


def _make_point(
    *,
    interval: dict[str, Any],
    dataset: str,
    band_name: str,
    stats: dict[str, Any],
) -> StatPoint | None:
    try:
        ifrom = _parse_iso(interval["from"])
        ito = _parse_iso(interval["to"])
    except (KeyError, ValueError):
        return None
    return StatPoint(
        interval_from=ifrom,
        interval_to=ito,
        dataset=dataset,
        band_name=band_name,
        mean=_maybe_float(stats.get("mean")),
        min_value=_maybe_float(stats.get("min")),
        max_value=_maybe_float(stats.get("max")),
        std_dev=_maybe_float(stats.get("stDev")),
        sample_count=int(stats.get("sampleCount") or 0),
    )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    if f != f:   # NaN guard — Statistical API emits NaN for fully-masked intervals
        return None
    return f


def _parse_iso(value: str) -> datetime:
    """RFC3339 with optional Z. fromisoformat in 3.11+ handles Z natively
    but we still normalise for safety."""
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
