"""GET /api/v1/cropguard/predictions — recent crop disease predictions.

Read-only consumer of `tenant_<id>.crop_predictions` (populated by the
ML service at apps/ml, see migration 0014). The X-Tenant-Id header
selects the tenant — middleware/tenant.py sets search_path so the bare
`crop_predictions` table resolves to the right schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.cropguard import (
    CropPredictionListData,
    CropPredictionRow,
    CropTopKEntry,
    LonLat,
    YieldForecastListData,
    YieldForecastRow,
)
from schemas.envelope import ResponseMeta, SuccessResponse


router = APIRouter(prefix="/cropguard", tags=["cropguard"])


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


@router.get(
    "/predictions",
    response_model=SuccessResponse[CropPredictionListData],
    summary="List recent crop disease predictions for a tenant",
    description=(
        "Returns the most recent rows from `tenant_<id>.crop_predictions`, "
        "newest first. `X-Tenant-Id` header is required."
    ),
)
async def list_predictions(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows to return (default 10).")
    ] = 10,
) -> SuccessResponse[CropPredictionListData]:
    _require_tenant(request)

    result = await session.execute(
        text(
            """
            SELECT id, tenant_id,
                   predicted_class, prediction, confidence, confidence_band,
                   requires_human_review, top_k,
                   image_source, image_s3_bucket, image_s3_key,
                   model_name, model_version, inference_time_ms,
                   created_at, lga,
                   ST_X(location) AS lon, ST_Y(location) AS lat
              FROM crop_predictions
             ORDER BY created_at DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    predictions = [_row_to_response(dict(r)) for r in rows]
    return SuccessResponse(
        data=CropPredictionListData(predictions=predictions),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


def _row_to_response(row: dict) -> CropPredictionRow:
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
        prediction=float(row["prediction"]),
        confidence=float(row["confidence"]),
        confidence_band=row["confidence_band"],
        requires_human_review=bool(row["requires_human_review"]),
        top_k=top_k,
        image_source=row["image_source"],
        image_s3_key=row.get("image_s3_key"),
        image_s3_bucket=row.get("image_s3_bucket"),
        location=(
            LonLat(lon=float(row["lon"]), lat=float(row["lat"]))
            if row.get("lon") is not None and row.get("lat") is not None
            else None
        ),
        lga=row.get("lga"),
        model_name=row["model_name"],
        model_version=row["model_version"],
        inference_time_ms=row.get("inference_time_ms"),
        created_at=row["created_at"],
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
