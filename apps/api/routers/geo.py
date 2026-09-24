"""Coordinate → administrative unit, from our own centroid dataset.

Why this exists: the dashboard used to label a coordinate by reverse-geocoding
it through Mapbox, which returns Mapbox's own spelling of the LGA and state.
That could disagree with the names used everywhere else in the platform — and
a field officer seeing one place named two ways is worse than seeing a coarse
name. This endpoint answers with the SAME names the alerts, crop-health rows
and reports use, because it reads the same 447-unit geoBoundaries dataset
(`services/lga_geo.py`).

Deliberately unauthenticated and DB-free: it is pure in-memory arithmetic over
open administrative geography, reveals no tenant data, and is called per row on
the Farm Check bulk path where a database round trip would be felt.

Not module-gated — `geo` is absent from PATH_PREFIX_TO_MODULE, so
ModuleAccessMiddleware passes it through like the other control-plane routes.

## What this endpoint does NOT do, and what callers must add

It answers "the nearest unit **we hold**", and we hold the ten pilots only. A
point just over the border in a non-pilot state therefore gets the closest pilot
unit, confidently and wrongly: measured at (4.60, 11.90) — Kebbe, in SOKOTO —
this returns `kebbi / Jega`, 30 km away and in the wrong state. `distance_km`
cannot flag it, because 30 km is an ordinary distance to a centroid.

The dashboard resolves this by cross-checking against Mapbox's region and
discarding our answer when the two disagree (`apps/frontend/src/lib/place.ts`).
Any NEW consumer must do something equivalent before presenting this as the
place a point is in — the raw answer is "nearest known unit", not "containing
unit".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.geo import ResolvedUnit
from schemas.places import NearestPlacesData
from services.lga_geo import nearest_unit
from services.places import nearest_places

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/resolve", response_model=SuccessResponse[ResolvedUnit])
async def resolve(
    request: Request,
    lon: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
) -> SuccessResponse[ResolvedUnit]:
    """Name the administrative unit nearest `(lon, lat)`.

    Returns an all-null body rather than a 404 when the point falls outside
    pilot coverage: "we don't know where this is" is a normal answer for a
    coordinate someone just typed, not an error worth an exception path.
    """
    hit = nearest_unit(lon, lat)
    data = (
        ResolvedUnit()
        if hit is None
        else ResolvedUnit(tenant_id=hit[0], lga=hit[1], distance_km=round(hit[2], 2))
    )
    return SuccessResponse(
        data=data,
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
    )


# Lookups ride on GET on purpose: the audit middleware records every POST as a
# mutation, and a village lookup must not show up as an action in the audit log
# or inflate a partner's activity figures.
MAX_POINTS = 100


def _parse_points(raw: str) -> list[tuple[float, float]]:
    """'lon,lat;lon,lat' -> [(lon, lat), ...], range-checked."""
    out: list[tuple[float, float]] = []
    for pair in filter(None, (p.strip() for p in raw.split(";"))):
        try:
            lon_s, lat_s = pair.split(",")
            lon, lat = float(lon_s), float(lat_s)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Bad point {pair!r}; use lon,lat") from None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise HTTPException(status_code=400, detail=f"Point {pair!r} is out of range")
        out.append((lon, lat))
    if not 1 <= len(out) <= MAX_POINTS:
        raise HTTPException(status_code=400, detail=f"Send 1-{MAX_POINTS} points")
    return out


@router.get("/nearest-places", response_model=SuccessResponse[NearestPlacesData])
async def nearest_places_for(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    points: Annotated[str, Query(max_length=6000, description="lon,lat pairs separated by ';'")],
) -> SuccessResponse[NearestPlacesData]:
    """The nearest named village for each point, in request order.

    For coordinates a person entered or checked — a Farm Check point, a bulk
    sheet — which are real points by construction. Detections carry their
    village on their own responses instead (services/places.py). GRID3
    settlement names, CC BY 4.0.
    """
    places = await nearest_places(session, _parse_points(points))
    return SuccessResponse(
        data=NearestPlacesData(places=places),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
    )
