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

from fastapi import APIRouter, Query, Request

from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.geo import ResolvedUnit
from services.lga_geo import nearest_unit

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
