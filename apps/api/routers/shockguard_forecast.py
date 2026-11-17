"""GET /api/v1/shockguard/forecast            — the next 15 days, LGA by LGA (ECMWF)
GET /api/v1/shockguard/forecast/cells      — ECMWF's own 0.25 deg cells, for the map
GET /api/v1/shockguard/forecast/check      — how the forecast did: the scorecard
GET /api/v1/shockguard/forecast/check/day  — one day: measured vs every forecast for it

The forecast side of ShockGuard. It ADDS to the observed side (IMERG rain,
storms, radar) and changes none of it: same prefix, so the same login, tenant
scoping and module entitlement apply, but its own tables and its own feed.
The check compares the two sides and alters neither.

The feed is deliberately NOT in routers/shockguard.LIVE_SCAN_SOURCES. That list
drives the observed side's feed rows and its "active shocks" counts from
shock_events; a forecast raises no events, and a row reading "no signal" for
it would be wrong. Its health is reported in this response instead, and the
daily watchdog watches it through services/feed_health.FEED_MAX_AGE_HOURS.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from repositories import forecast as repo
from repositories import forecast_check as check_repo
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.forecast import ForecastArea, ForecastCellsData, ForecastData, ForecastFeed
from schemas.forecast_check import (
    CheckDayArea,
    CheckLga,
    ForecastCheckData,
    ForecastCheckDayData,
)
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


_SUMMARY_FIELDS = (
    "first_day", "last_day", "days_checked", "lga_days", "pairs", "wet_mm", "heavy_mm", "shown_leads",
    "chance_bins", "chance_groups", "recent_days", "recent_from", "scorecard", "chances", "ribbon",
)


@router.get(
    "/forecast/check",
    response_model=SuccessResponse[ForecastCheckData],
    summary="How the forecast did: ECMWF's rain forecast against NASA IMERG, per LGA",
)
async def get_forecast_check(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ForecastCheckData]:
    """The newest scorecard: wet-day hits, misses and false alarms by model and
    by how many days ahead the forecast was made, the ensemble's chances against
    what happened, recent days, and each LGA's own record.

    IMERG is a satellite estimate, not a rain gauge: this is how often two
    independent estimates agree, not an accuracy against ground truth.
    """
    tenant_id = _require_tenant(request)
    row = await check_repo.latest_summary(session)
    feed = ForecastFeed(**await repo.feed_status(session, tenant_id, source=check_repo.CHECK_SOURCE))
    if row is None:
        return SuccessResponse(data=ForecastCheckData(feed=feed), meta=_meta(request))
    s = row["summary"]
    lgas = [CheckLga(**r, location=_location(tenant_id, r["lga"])) for r in s.get("lgas", [])]
    return SuccessResponse(
        data=ForecastCheckData(
            computed_at=row["created_at"], lgas=lgas, feed=feed,
            **{k: s[k] for k in _SUMMARY_FIELDS if k in s},
        ),
        meta=_meta(request),
    )


@router.get(
    "/forecast/check/day",
    response_model=SuccessResponse[ForecastCheckDayData],
    summary="One measured day: the rain IMERG measured per LGA and every forecast made for it",
)
async def get_forecast_check_day(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    day: Annotated[date | None, Query(description="UTC day; defaults to the newest measured")] = None,
) -> SuccessResponse[ForecastCheckDayData]:
    """Per LGA: the measured rain and the forecasts for that day made 0..14 days
    before it, physics and AI models, plus the ensemble's chances to 10 days."""
    tenant_id = _require_tenant(request)
    when = day or await check_repo.newest_measured_day(session)
    if when is None:
        return SuccessResponse(data=ForecastCheckDayData(), meta=_meta(request))
    rows = await check_repo.check_day(session, when)
    areas = [CheckDayArea(**r, location=_location(tenant_id, r["lga"])) for r in rows]
    return SuccessResponse(data=ForecastCheckDayData(day=when, areas=areas), meta=_meta(request))
