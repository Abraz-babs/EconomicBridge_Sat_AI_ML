"""GET /api/v1/cropguard/predictions — recent crop disease predictions.

Read-only consumer of `tenant_<id>.crop_predictions` (populated by the
ML service at apps/ml, see migration 0014). The X-Tenant-Id header
selects the tenant — middleware/tenant.py sets search_path so the bare
`crop_predictions` table resolves to the right schema.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.cropguard import (
    CropSeasonData,
    CropSeasonLga,
    CropSeasonPatch,
    CropHealthListData,
    CropHealthRow,
    CropPredictionListData,
    CropPredictionRow,
    CropTopKEntry,
    LonLat,
    YieldForecastListData,
    YieldForecastRow,
)
from schemas.envelope import ResponseMeta, SuccessResponse
from services import lga_geo
from services.places import nearest_places


router = APIRouter(prefix="/cropguard", tags=["cropguard"])

# scripts/seed_cropguard_predictions.py stamps placeholder rows with a
# `*-seed` model_version (currently "0.0.0-seed") so they stay identifiable.
# Those rows are demo scaffolding, never real inference, and must not reach
# the Disease Geography map — a blank map is honest, fabricated pins are not.
SEED_VERSION_PATTERN = "%-seed"


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required for this endpoint",
        )
    return tenant_id


class LgaListData(BaseModel):
    tenant_id: str
    lgas: list[str]


@router.get(
    "/lgas",
    response_model=SuccessResponse[LgaListData],
    summary="List the LGAs/districts for the active tenant (for record tagging)",
)
async def list_lgas(request: Request) -> SuccessResponse[LgaListData]:
    """LGA names for the active tenant — populates the Leaf Diagnosis LGA picker
    so saved field records carry a consistent place tag."""
    tenant_id = _require_tenant(request)
    return SuccessResponse(
        data=LgaListData(tenant_id=tenant_id, lgas=lga_geo.all_lgas(tenant_id)),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


@router.get(
    "/predictions",
    response_model=SuccessResponse[CropPredictionListData],
    summary="List recent crop disease predictions for a tenant",
    description=(
        "Returns the most recent rows from `tenant_<id>.crop_predictions`, "
        "newest first. `X-Tenant-Id` header is required. Placeholder rows "
        "written by scripts/seed_cropguard_predictions.py (model_version "
        "`*-seed`) are never served — see the WHERE clause below."
    ),
)
async def list_predictions(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows to return (default 10).")
    ] = 10,
) -> SuccessResponse[CropPredictionListData]:
    tenant_id = _require_tenant(request)

    result = await session.execute(
        text(
            """
            SELECT id, tenant_id,
                   predicted_class, abstained, abstain_reason,
                   prediction, confidence, confidence_band,
                   requires_human_review, top_k,
                   image_source, image_s3_bucket, image_s3_key,
                   model_name, model_version, inference_time_ms,
                   created_at, lga, zone_name,
                   ST_X(location) AS lon, ST_Y(location) AS lat
              FROM crop_predictions
             -- Seed rows are synthetic placeholders, not inference. Serving
             -- them puts fabricated diagnoses on the Disease Geography map,
             -- which is a credibility risk in front of an agency. An honest
             -- empty map is correct until a real leaf photo is uploaded.
             -- COALESCE keeps rows whose model_version is NULL (NULL NOT LIKE
             -- is NULL, which would silently drop real inference rows). The
             -- pattern is bound, not inlined, so no %-escaping ambiguity
             -- between the asyncpg and psycopg paramstyles.
             WHERE COALESCE(model_version, '') NOT LIKE :seed_pattern
               AND NOT is_deleted
             ORDER BY created_at DESC
             LIMIT :limit
            """
        ),
        {"limit": limit, "seed_pattern": SEED_VERSION_PATTERN},
    )
    rows = result.mappings().all()

    predictions = [_row_to_response(dict(r), tenant_id) for r in rows]
    # Field directions only where the photo carried real GPS — a tagged LGA's
    # centroid is not the farm.
    places = await nearest_places(session, [
        (p.location.lon, p.location.lat)
        if p.location and p.location_source == "gps" else None
        for p in predictions
    ])
    for p, place in zip(predictions, places):
        p.nearest_place = place
    return SuccessResponse(
        data=CropPredictionListData(predictions=predictions),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


def _location_for(row: dict, tenant_id: str | None) -> LonLat | None:
    """Real GPS if the photo had it, else the tagged LGA's true centroid."""
    if row.get("lon") is not None and row.get("lat") is not None:
        return LonLat(lon=float(row["lon"]), lat=float(row["lat"]))
    lga = row.get("lga")
    if tenant_id and lga:
        try:
            lon, lat = lga_geo.centroid_for(tenant_id, lga)
        except KeyError:
            return None      # unknown LGA name — no position beats a wrong one
        return LonLat(lon=lon, lat=lat)
    return None


def _location_source(row: dict, tenant_id: str | None) -> str:
    """How the coordinates were arrived at, so the UI never implies a survey."""
    if row.get("lon") is not None and row.get("lat") is not None:
        return "gps"
    if tenant_id and row.get("lga"):
        try:
            lga_geo.centroid_for(tenant_id, row["lga"])
        except KeyError:
            return "none"
        return "lga_centroid"
    return "none"


def _row_to_response(row: dict, tenant_id: str | None = None) -> CropPredictionRow:
    """Map a raw mapping from `crop_predictions` to its Pydantic shape.

    `top_k` rides through Postgres as JSONB; asyncpg/SQLAlchemy hands us
    a Python list[dict] already so the parse step is just pydantic
    validation."""
    raw_top_k = row.get("top_k") or []
    top_k = [
        CropTopKEntry(
            class_name=entry["class_name"],
            probability=float(entry["probability"]),
        )
        for entry in raw_top_k
    ]
    return CropPredictionRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        predicted_class=row["predicted_class"],
        abstained=bool(row.get("abstained", False)),
        abstain_reason=row.get("abstain_reason"),
        prediction=float(row["prediction"]),
        confidence=float(row["confidence"]),
        confidence_band=row["confidence_band"],
        requires_human_review=bool(row["requires_human_review"]),
        top_k=top_k,
        image_source=row["image_source"],
        image_s3_key=row.get("image_s3_key"),
        image_s3_bucket=row.get("image_s3_bucket"),
        # A leaf photo usually carries no GPS, and the map still has to put the
        # pin somewhere. It used to be placed by the FRONTEND at a hashed
        # bearing 0.25-0.85 degrees (28-95 km) from the STATE centroid, which
        # scattered pins across neighbouring LGAs and sometimes out of the state
        # entirely — an authority reading the halo was sent to the wrong place.
        #
        # We hold 447 real geoBoundaries LGA centroids, so use the centroid of
        # the LGA the operator actually tagged. Still not the farm, and the
        # response says so via `location_source`; but it is inside the right
        # administrative unit, which is the claim the map is making.
        location=_location_for(row, tenant_id),
        location_source=_location_source(row, tenant_id),
        lga=row.get("lga"),
        zone_name=row.get("zone_name"),
        model_name=row["model_name"],
        model_version=row["model_version"],
        inference_time_ms=row.get("inference_time_ms"),
        created_at=row["created_at"],
    )


# ─── Statewide per-LGA crop health (Sentinel-2 NDVI) ──────────────────────


@router.get(
    "/crop-health",
    response_model=SuccessResponse[CropHealthListData],
    summary="Current per-LGA crop/vegetation health for the tenant (every LGA)",
    description=(
        "One row per LGA with its latest Sentinel-2 NDVI health "
        "(healthy/moderate/stressed/poor). Populated by the per-LGA satellite "
        "sweep so the CropGuard map covers every LGA, not only photo uploads."
    ),
)
async def list_crop_health(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=2000, description="Max rows (default 600).")
    ] = 600,
) -> SuccessResponse[CropHealthListData]:
    _require_tenant(request)
    result = await session.execute(
        text(
            """
            SELECT id, tenant_id, lga,
                   ST_X(location) AS lon, ST_Y(location) AS lat,
                   ndvi, ndvi_date, health, verdict, source, created_at
              FROM crop_health
             ORDER BY lga
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    out = [
        CropHealthRow(
            id=r["id"], tenant_id=r["tenant_id"], lga=r["lga"],
            lat=float(r["lat"]), lon=float(r["lon"]),
            ndvi=(float(r["ndvi"]) if r.get("ndvi") is not None else None),
            ndvi_date=(r["ndvi_date"].isoformat() if r.get("ndvi_date") else None),
            health=r["health"], verdict=r.get("verdict") or "",
            source=r.get("source") or "crop_health_v1", created_at=r["created_at"],
        )
        for r in rows
    ]
    return SuccessResponse(
        data=CropHealthListData(rows=out),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )


# ─── Yield forecasts (Slice 04.c) ─────────────────────────────────────────


@router.get(
    "/yield/forecasts",
    response_model=SuccessResponse[YieldForecastListData],
    summary="List recent yield predictions for a tenant",
    description=(
        "Returns the most recent rows from `tenant_<id>.yield_predictions`, "
        "newest first. Optional `crop` filter narrows to one staple. "
        "`X-Tenant-Id` header is required."
    ),
)
async def list_yield_forecasts(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows (default 30).")
    ] = 30,
    crop: Annotated[
        str | None, Query(max_length=40, description="Filter to one crop.")
    ] = None,
) -> SuccessResponse[YieldForecastListData]:
    _require_tenant(request)

    if crop:
        result = await session.execute(
            text(
                """
                SELECT id, tenant_id, crop,
                       prediction, confidence, confidence_band,
                       requires_human_review,
                       predicted_yield_t_ha, yield_pi_low_t_ha, yield_pi_high_t_ha,
                       model_name, model_version, inference_time_ms,
                       created_at
                  FROM yield_predictions
                 WHERE crop = :crop
                 ORDER BY created_at DESC
                 LIMIT :limit
                """
            ),
            {"crop": crop.strip().lower(), "limit": limit},
        )
    else:
        result = await session.execute(
            text(
                """
                SELECT id, tenant_id, crop,
                       prediction, confidence, confidence_band,
                       requires_human_review,
                       predicted_yield_t_ha, yield_pi_low_t_ha, yield_pi_high_t_ha,
                       model_name, model_version, inference_time_ms,
                       created_at
                  FROM yield_predictions
                 ORDER BY created_at DESC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    rows = result.mappings().all()

    forecasts = [
        YieldForecastRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            crop=r["crop"],
            prediction=float(r["prediction"]),
            confidence=float(r["confidence"]),
            confidence_band=r["confidence_band"],
            requires_human_review=bool(r["requires_human_review"]),
            predicted_yield_t_ha=float(r["predicted_yield_t_ha"]),
            yield_pi_low_t_ha=(
                float(r["yield_pi_low_t_ha"])
                if r.get("yield_pi_low_t_ha") is not None else None
            ),
            yield_pi_high_t_ha=(
                float(r["yield_pi_high_t_ha"])
                if r.get("yield_pi_high_t_ha") is not None else None
            ),
            model_name=r["model_name"],
            model_version=r["model_version"],
            inference_time_ms=r.get("inference_time_ms"),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return SuccessResponse(
        data=YieldForecastListData(forecasts=forecasts),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


@router.delete(
    "/predictions/{prediction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a diagnosis from the feed (soft delete)",
)
async def delete_prediction(
    prediction_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Retire a test upload or a mistaken photo from the operator's view.

    Soft delete (CLAUDE.md §4.4): the row is flagged, never destroyed. That
    matters more here than elsewhere — an abstention records an image the model
    could not handle, which is exactly the retraining material we need.
    Removing it from the feed must not remove it from the evidence.
    """
    _require_tenant(request)
    result = await session.execute(
        text(
            "UPDATE crop_predictions SET is_deleted = TRUE "
            "WHERE id = :id AND NOT is_deleted"
        ),
        {"id": prediction_id},
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction not found",
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Season watch ────────────────────────────────────────────────────────────

LAND_CHANGE_MODEL = "land_change_v1"
SEASON_PATCHES = 30
_PEAKS = re.compile(r"peak greenness ([0-9.]+) to ([0-9.]+)")


def _patch_kind(summary: str | None) -> str:
    s = (summary or "").lower()
    if "crops that" in s:
        return "crops"
    if "rangeland that" in s:
        return "rangeland"
    return "farmland"


def _season_lgas(
    veg: list[Mapping[str, Any]],
    changes: dict[str, int],
    centroid: Any = None,
) -> tuple[list[CropSeasonLga], int | None, int | None]:
    """One row per LGA across the seasons held. Pure, for testing.

    Farmland = crops + rangeland that greened. The like-for-like change is the
    latest season against the one before, over the ground BOTH saw — the only
    honest comparison when cloud hides seasons unequally.
    """
    years = sorted({int(v["season_year"]) for v in veg})
    latest = years[-1] if years else None
    prev = years[-2] if len(years) > 1 else None
    by: dict[str, dict[str, Any]] = {}
    for v in veg:
        row = by.setdefault(v["lga"], {"lga": v["lga"], "farmland_ha": {}})
        y = int(v["season_year"])
        crops = v.get("greened_on_crops_ha")
        rng = v.get("greened_on_rangeland_ha")
        if crops is not None or rng is not None:
            row["farmland_ha"][y] = round(float(crops or 0) + float(rng or 0), 1)
        if y == latest:
            row["crops_ha"] = round(float(crops), 1) if crops is not None else None
            common, prev_common = v.get("greened_ha_common"), v.get("prev_greened_ha_common")
            if common and prev_common:
                row["like_for_like_pct"] = round(100.0 * (float(common) / float(prev_common) - 1.0), 1)
            if v.get("common_observed_ha") and v.get("lga_ha"):
                row["seen_pct"] = round(100.0 * float(v["common_observed_ha"]) / float(v["lga_ha"]))
    out = []
    for lga, row in by.items():
        loc = None
        if centroid is not None:
            c = centroid(lga)
            if c is not None:
                loc = LonLat(lon=c[0], lat=c[1])
        out.append(CropSeasonLga(**row, location=loc, stopped_growing=int(changes.get(lga, 0))))
    out.sort(key=lambda r: (r.like_for_like_pct is None, r.like_for_like_pct if r.like_for_like_pct is not None else 0.0))
    return out, latest, prev


@router.get(
    "/season",
    response_model=SuccessResponse[CropSeasonData],
    summary="This rainy season against the last, LGA by LGA, and the land that stopped growing",
)
async def crop_season(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[CropSeasonData]:
    """Season watch: farmland greenness this rainy season against the last,
    over the ground both could see (Copernicus Sentinel-2, every farmland
    pixel), and the patches that stopped growing, each with its nearest named
    village. Greenness is a lead for an officer to check, not a diagnosis.
    """
    tenant_id = _require_tenant(request)
    meta = ResponseMeta(tenant_id=None, trace_id=getattr(request.state, "trace_id", uuid4()),
                        timestamp=datetime.now(timezone.utc), pagination=None)
    has = (await session.execute(text(
        "SELECT to_regclass('lga_season_vegetation') IS NOT NULL"
    ))).scalar()
    if not has:
        return SuccessResponse(data=CropSeasonData(), meta=meta)

    veg = (await session.execute(text(
        """
        SELECT lga, season_year, lga_ha, greened_on_crops_ha, greened_on_rangeland_ha,
               greened_ha_common, prev_greened_ha_common, common_observed_ha, window_end
          FROM lga_season_vegetation
         WHERE detector_version = :dv
        """
    ), {"dv": LAND_CHANGE_MODEL})).mappings().all()
    alerts = (await session.execute(text(
        """
        SELECT lga, zone_name, affected_area_ha, created_at,
               ST_X(location) AS lon, ST_Y(location) AS lat
          FROM alert_events WHERE model_version = :m
         ORDER BY affected_area_ha DESC NULLS LAST
        """
    ), {"m": LAND_CHANGE_MODEL})).mappings().all()

    changes: dict[str, int] = {}
    for a in alerts:
        if a["lga"]:
            changes[a["lga"]] = changes.get(a["lga"], 0) + 1

    def centroid(lga: str) -> tuple[float, float] | None:
        try:
            return lga_geo.centroid_for(tenant_id, lga)
        except KeyError:
            return None

    lgas, latest, prev = _season_lgas(veg, changes, centroid)

    top = alerts[:SEASON_PATCHES]
    places = await nearest_places(session, [
        (a["lon"], a["lat"]) if a["lon"] is not None and a["lat"] is not None else None for a in top
    ])
    patches = []
    for a, place in zip(top, places):
        m = _PEAKS.search(a["zone_name"] or "")
        patches.append(CropSeasonPatch(
            lga=a["lga"], kind=_patch_kind(a["zone_name"]),
            area_ha=a["affected_area_ha"],
            peak_before=float(m.group(1)) if m else None,
            peak_now=float(m.group(2)) if m else None,
            location=LonLat(lon=a["lon"], lat=a["lat"]) if a["lon"] is not None else None,
            detected_at=a["created_at"], summary=a["zone_name"], nearest_place=place,
        ))

    latest_rows = [v for v in veg if latest is not None and int(v["season_year"]) == latest]
    common = sum(float(v["greened_ha_common"] or 0) for v in latest_rows)
    prev_common = sum(float(v["prev_greened_ha_common"] or 0) for v in latest_rows)
    kinds = [_patch_kind(a["zone_name"]) for a in alerts]
    data = CropSeasonData(
        season_year=latest, previous_year=prev,
        years=sorted({int(v["season_year"]) for v in veg}),
        window_end=max((v["window_end"] for v in latest_rows), default=None),
        lgas=lgas,
        farmland_ha=round(sum(r.farmland_ha.get(latest, 0.0) for r in lgas), 1) if latest else 0.0,
        like_for_like_pct=round(100.0 * (common / prev_common - 1.0), 1) if prev_common else None,
        stopped_growing=len(alerts),
        stopped_crops=kinds.count("crops"),
        stopped_rangeland=kinds.count("rangeland"),
        patches=patches,
    )
    return SuccessResponse(data=data, meta=meta)

