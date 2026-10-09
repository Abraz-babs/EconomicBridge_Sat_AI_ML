"""POST /api/v1/cropguard/farm-check — on-demand single-farm vegetation check.

Takes a coordinate + crop type, queries Copernicus Sentinel-2 NDVI and
Sentinel-1 SAR over a small box around the point, and returns a crop-aware
vegetation-health verdict. This is a fast single CDSE call (small bbox), so it
runs on the request path — unlike the multi-tenant ingest sweeps.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sources.claim_check import EARLIEST_LOSS, check_claim
from sources.copernicus import CopernicusClient, CopernicusError
from sources.farm_check import FarmCheckResult, check_farm
from sources.sentinel_statistical import SentinelStatisticalClient

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cropguard", tags=["cropguard"])

# Module-level client so the OAuth token cache is reused across requests.
_client: SentinelStatisticalClient | None = None


def _get_client() -> SentinelStatisticalClient:
    global _client
    if _client is None:
        _client = SentinelStatisticalClient(CopernicusClient())
    return _client


class FarmCheckRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Farm latitude (WGS84).")
    lon: float = Field(ge=-180, le=180, description="Farm longitude (WGS84).")
    crop: str = Field(default="general", max_length=40,
                      description="Crop being checked, e.g. 'maize'. Leave blank or 'general' "
                                  "for a crop-agnostic reading (the satellite grades vigour itself).")
    half_m: int = Field(
        default=120, ge=30, le=1000,
        description="Half the box side in metres around the point (30–1000).",
    )


class TrendPoint(BaseModel):
    date: str
    ndvi: float


class PassPoint(BaseModel):
    date: str
    ndvi: float
    health: str
    verdict: str
    sample_count: int
    cloud_affected: bool


class StressInfo(BaseModel):
    level: str          # none | moderate | high | unknown
    z: float | None
    message: str


class FarmCheckResponse(BaseModel):
    lat: float
    lon: float
    crop: str
    ndvi: float | None
    ndvi_date: str | None
    health: str
    verdict: str
    sar_db: float | None
    sar_date: str | None
    trend: list[TrendPoint]
    passes: list[PassPoint]
    stress: StressInfo
    sample_count: int
    area_ha: float
    resolution_m: int
    source: str
    note: str


def _to_response(r: FarmCheckResult) -> FarmCheckResponse:
    return FarmCheckResponse(
        lat=r.lat, lon=r.lon, crop=r.crop,
        ndvi=r.ndvi, ndvi_date=r.ndvi_date,
        health=r.health, verdict=r.verdict,
        sar_db=r.sar_db, sar_date=r.sar_date,
        trend=[TrendPoint(**p) for p in r.trend],
        passes=[PassPoint(**p) for p in r.passes],
        stress=StressInfo(**r.stress),
        sample_count=r.sample_count, area_ha=r.area_ha,
        resolution_m=r.resolution_m, source=r.source, note=r.note,
    )


class ClaimCheckRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Plot latitude (WGS84).")
    lon: float = Field(ge=-180, le=180, description="Plot longitude (WGS84).")
    loss_date: date = Field(description="Date the loss was reported to have happened.")
    peril: Literal["flood", "drought", "general"] = Field(
        default="flood", description="The insured peril claimed.")
    crop: str = Field(default="general", max_length=40)
    half_m: int = Field(default=60, ge=30, le=1000,
                        description="Half the box side in metres around the point.")


class ClaimCheckResponse(BaseModel):
    lat: float
    lon: float
    loss_date: str
    peril: str
    crop: str
    area_ha: float
    windows: dict[str, str]
    thresholds: dict[str, float]
    ndvi_passes: list[dict]
    water_passes: list[dict]
    metrics: dict[str, float | None]
    flood_evidence: str
    vegetation_change: str
    conclusion: str
    summary: str
    recommendation: str
    limitations: list[str]
    source: str


@router.post(
    "/claim-check",
    response_model=ClaimCheckResponse,
    summary="Satellite evidence on one insured plot before and after a loss date",
)
async def claim_check(body: ClaimCheckRequest) -> ClaimCheckResponse:
    today = datetime.now(timezone.utc).date()
    if body.loss_date > today:
        raise HTTPException(status_code=422, detail="The loss date is in the future.")
    if body.loss_date < EARLIEST_LOSS:
        raise HTTPException(status_code=422,
                            detail=f"Loss dates before {EARLIEST_LOSS.isoformat()} are not supported.")
    client = _get_client()
    if not client.configured:
        raise HTTPException(
            status_code=503,
            detail="Satellite data source not configured (no Copernicus credentials).",
        )
    try:
        result = await check_claim(
            client, lat=body.lat, lon=body.lon, loss_date=body.loss_date,
            peril=body.peril, crop=body.crop, half_m=body.half_m, today=today,
        )
    except CopernicusError as exc:
        log.warning("claim-check CDSE error lat=%s lon=%s: %s", body.lat, body.lon, exc)
        raise HTTPException(status_code=502, detail=f"Satellite query failed: {exc!s}") from exc
    return ClaimCheckResponse(**asdict(result))


@router.post(
    "/farm-check",
    response_model=FarmCheckResponse,
    summary="Per-farm Sentinel-2 NDVI + Sentinel-1 SAR vegetation health",
)
async def farm_check(body: FarmCheckRequest) -> FarmCheckResponse:
    client = _get_client()
    if not client.configured:
        raise HTTPException(
            status_code=503,
            detail="Satellite data source not configured (no Copernicus credentials).",
        )
    try:
        result = await check_farm(
            client, lat=body.lat, lon=body.lon, crop=body.crop, half_m=body.half_m,
        )
    except CopernicusError as exc:
        log.warning("farm-check CDSE error lat=%s lon=%s: %s", body.lat, body.lon, exc)
        raise HTTPException(status_code=502, detail=f"Satellite query failed: {exc!s}") from exc
    return _to_response(result)
