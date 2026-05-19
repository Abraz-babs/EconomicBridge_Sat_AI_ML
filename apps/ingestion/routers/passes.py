"""GET /api/v1/passes/upcoming — when satellites pass over a tenant.

Live N2YO call. Stateless — we do not persist passes here yet (that
arrives in Phase A.4 with the scheduler). For now this endpoint lets
the dashboard answer "when does Sentinel-1A next pass over Kebbi?".

Quota: N2YO free tier is 1000 transactions/hour. Each satellite + tenant
combination = one transaction. With 4 satellites x 10 tenants = 40
transactions per full sweep, we're nowhere near the cap.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from db import is_valid_tenant_id
from sources.n2yo import (
    SATELLITE_CATALOG,
    N2yoClient,
    N2yoError,
)
from sources.nasa_firms import PILOT_BBOX

router = APIRouter(prefix="/passes", tags=["passes"])

# Default satellite group → satellites we query. Caller can override.
DEFAULT_SATELLITES: tuple[str, ...] = (
    "SENTINEL-1A",
    "SENTINEL-2A",
    "SENTINEL-2B",
    "SUOMI-NPP",
)


# ─── Response schemas ──────────────────────────────────────────────────────


class PassResponse(BaseModel):
    satellite_name: str
    satellite_group: str
    norad_id: int
    observer_lat: float
    observer_lon: float
    start_utc: datetime
    max_utc: datetime
    end_utc: datetime
    max_elevation_deg: float
    max_azimuth_compass: str
    duration_seconds: int


class PassesUpcomingResponse(BaseModel):
    tenant_id: str
    observer_lat: float
    observer_lon: float
    days: int
    min_elevation_deg: int
    satellites_queried: list[str]
    passes: list[PassResponse]
    total: int


# ─── Centroid helper ───────────────────────────────────────────────────────


def _centroid_for(tenant_id: str) -> tuple[float, float]:
    """Return (lat, lon) at the centre of the tenant's PILOT_BBOX."""
    w, s, e, n = PILOT_BBOX[tenant_id]
    return ((s + n) / 2.0, (w + e) / 2.0)


# ─── Endpoint ──────────────────────────────────────────────────────────────


@router.get(
    "/upcoming",
    response_model=PassesUpcomingResponse,
    summary="Upcoming satellite passes over a tenant ROI",
)
async def upcoming_passes(
    tenant_id: Annotated[
        str, Query(min_length=1, max_length=50, description="Tenant slug (e.g. 'kebbi').")
    ],
    days: Annotated[
        int, Query(ge=1, le=10, description="Look-ahead window in days (N2YO max 10).")
    ] = 2,
    min_elevation: Annotated[
        int,
        Query(
            ge=1,
            le=90,
            description="Reject passes whose peak elevation is below this many degrees.",
        ),
    ] = 30,
    satellites: Annotated[
        list[str] | None,
        Query(
            description=(
                "Satellites to query (catalog keys). Default = "
                "Sentinel-1A + Sentinel-2A + Sentinel-2B + Suomi-NPP."
            ),
        ),
    ] = None,
) -> PassesUpcomingResponse:
    """Return all qualifying passes for the requested satellites over a tenant.

    Empty `passes` is a valid answer — it means nothing qualifies in the
    window. The caller should never interpret "no passes" as "service down".
    """
    tid = tenant_id.strip().lower()
    if not is_valid_tenant_id(tid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tid!r}",
        )

    sat_keys = list(satellites) if satellites else list(DEFAULT_SATELLITES)
    unknown = [s for s in sat_keys if s not in SATELLITE_CATALOG]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown satellite(s): {unknown}. "
            f"Valid keys: {sorted(SATELLITE_CATALOG)}",
        )

    lat, lon = _centroid_for(tid)
    client = N2yoClient()

    all_passes: list[PassResponse] = []
    try:
        for sat_key in sat_keys:
            passes = await client.fetch_passes(
                satellite_key=sat_key,
                observer_lat=lat,
                observer_lon=lon,
                days=days,
                min_elevation=min_elevation,
            )
            all_passes.extend(
                PassResponse(
                    satellite_name=p.satellite_name,
                    satellite_group=p.satellite_group,
                    norad_id=p.norad_id,
                    observer_lat=p.observer_lat,
                    observer_lon=p.observer_lon,
                    start_utc=p.start_utc,
                    max_utc=p.max_utc,
                    end_utc=p.end_utc,
                    max_elevation_deg=p.max_elevation_deg,
                    max_azimuth_compass=p.max_azimuth_compass,
                    duration_seconds=p.duration_seconds,
                )
                for p in passes
            )
    except N2yoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"N2YO upstream error: {exc}",
        ) from exc

    # Sort all passes by start time, regardless of satellite — the
    # dashboard wants a unified "next 5 things to wake up for" list.
    all_passes.sort(key=lambda p: p.start_utc)

    return PassesUpcomingResponse(
        tenant_id=tid,
        observer_lat=lat,
        observer_lon=lon,
        days=days,
        min_elevation_deg=min_elevation,
        satellites_queried=sat_keys,
        passes=all_passes,
        total=len(all_passes),
    )
