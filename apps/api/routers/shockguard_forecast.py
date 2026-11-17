"""GET /api/v1/shockguard/forecast        — the next 15 days, LGA by LGA (ECMWF)
GET /api/v1/shockguard/forecast/cells  — ECMWF's own 0.25 deg cells, for the map

The forecast side of ShockGuard. It ADDS to the observed side (IMERG rain,
storms, radar) and changes none of it: same prefix, so the same login, tenant
scoping and module entitlement apply, but its own tables and its own feed.

The feed is deliberately NOT in routers/shockguard.LIVE_SCAN_SOURCES. That list
drives the observed side's feed rows and its "active shocks" counts from
shock_events; a forecast raises no events, and a row reading "no signal" for
it would be wrong. Its health is reported in this response instead, and the
daily watchdog watches it through services/feed_health.FEED_MAX_AGE_HOURS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from repositories import forecast as repo
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.forecast import ForecastArea, ForecastCellsData, ForecastData, ForecastFeed
from schemas.shockguard import LonLat
from services import lga_geo

router = APIRouter(prefix="/shockguard", tags=["shockguard"])

FORECAST_DAYS = 15


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required for this endpoint",
        )
    return tenant_id


def _meta(request: Request) -> ResponseMeta:
    trace: UUID = getattr(request.state, "trace_id", uuid4())
    return ResponseMeta(tenant_id=None, trace_id=trace,
                        timestamp=datetime.now(timezone.utc), pagination=None)


def _location(tenant_id: str, lga: str) -> LonLat | None:
    try:
        lon, lat = lga_geo.centroid_for(tenant_id, lga)
    except KeyError:
        return None
    return LonLat(lon=lon, lat=lat)


@router.get(
    "/forecast",
    response_model=SuccessResponse[ForecastData],
    summary="Next 15 days per LGA from ECMWF (physics model, AI model, ensemble chances)",
)
async def get_forecast(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ForecastData]:
    """The newest stored 00 UTC run for the tenant, every LGA.

    A forecast, not a measurement: 0.25 deg cells (about 28 km) averaged over
    each LGA. An empty `areas` list means no run has been stored yet; `feed`
    says whether the feed has run and how it went.
    """
    tenant_id = _require_tenant(request)
    rows = await repo.latest_forecast(session)
    feed = ForecastFeed(**await repo.feed_status(session, tenant_id))
    if not rows:
        return SuccessResponse(data=ForecastData(feed=feed), meta=_meta(request))
    first = rows[0]["first_day"]
    areas = [
        ForecastArea(
            lga=r["lga"], location=_location(tenant_id, r["lga"]), cells=r["cells"],
            rain_ifs_mm=r["rain_ifs_mm"] or [], rain_ifs_max_mm=r["rain_ifs_max_mm"] or [],
            rain_aifs_mm=r["rain_aifs_mm"], chance_1mm=r["chance_1mm"],
            chance_10mm=r["chance_10mm"], chance_25mm=r["chance_25mm"],
            chance_50mm=r["chance_50mm"], temp_dawn_c=r["temp_dawn_c"],
            temp_afternoon_c=r["temp_afternoon_c"],
        )
        for r in rows
    ]
    return SuccessResponse(
        data=ForecastData(
            run_at=rows[0]["run_at"], first_day=first,
            days=[first + timedelta(days=d) for d in range(FORECAST_DAYS)],
            areas=areas, feed=feed,
        ),
        meta=_meta(request),
    )


@router.get(
    "/forecast/cells",
    response_model=SuccessResponse[ForecastCellsData],
    summary="ECMWF's own 0.25 deg forecast cells over the tenant",
)
async def get_forecast_cells(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ForecastCellsData]:
    """Raw cells of the newest run, for the map layer that shows ECMWF's grid
    instead of LGA averages. Empty before the first run."""
    _require_tenant(request)
    row = await repo.latest_cells(session)
    if row is None:
        return SuccessResponse(data=ForecastCellsData(), meta=_meta(request))
    return SuccessResponse(
        data=ForecastCellsData(
            run_at=row["run_at"], lat0=row["lat0"], lon0=row["lon0"], res=row["res"],
            n_rows=row["n_rows"], n_cols=row["n_cols"], rain_ifs_mm=row["rain_ifs_mm"] or [],
            rain_aifs_mm=row["rain_aifs_mm"], chance_10mm=row["chance_10mm"],
        ),
        meta=_meta(request),
    )
