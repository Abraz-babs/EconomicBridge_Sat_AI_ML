"""POST /api/v1/predict/crop_disease/tiled — multi-tile CropGuard inference.

Slice 5e-a. Chops a user-supplied field photo into a rows × cols grid,
predicts on each tile via the existing CropClassifier, and returns one
record per tile plus the headline "hottest" tile. One row per analysis
gets written to `tenant_<id>.crop_predictions` (the aggregate row);
per-tile details ride in the `top_k` JSONB column so the dashboard can
re-render them later.

Becomes the inner loop of the Sentinel-2 pipeline (Slice 5e-b) once
the CDSE-download blocker clears.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id, set_tenant_schema
from models.crop_classifier import get_classifier
from schemas.crop import (
    CropTopKEntryResponse,
    CropTiledPredictionData,
    CropTiledPredictionRequest,
    TileResultResponse,
)
from schemas.envelope import ResponseMeta, SuccessResponse
from services.tiled_inference import TiledInferenceResult, tile_and_predict


log = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/crop_disease/tiled",
    response_model=SuccessResponse[CropTiledPredictionData],
    summary="Multi-tile CropGuard inference on a wide field photo",
)
async def predict_crop_disease_tiled(
    body: CropTiledPredictionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[CropTiledPredictionData]:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )

    image_bytes = base64.b64decode(body.image_base64, validate=True)
    classifier = get_classifier()
    trace = _trace_id(request)

    try:
        result = tile_and_predict(
            tenant_id=tenant_id,
            image_bytes=image_bytes,
            classifier=classifier,
            rows=body.rows,
            cols=body.cols,
            top_k=body.top_k,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    prediction_id: UUID | None = None
    persisted = False
    if body.persist:
        prediction_id = await _persist_tiled(
            session,
            tenant_id=tenant_id, body=body, result=result, trace_id=trace,
        )
        persisted = prediction_id is not None

    return SuccessResponse(
        data=CropTiledPredictionData(
            prediction_id=prediction_id,
            model_name=result.model_name,
            model_version=result.model_version,
            tenant_id=result.tenant_id,
            rows=result.rows, cols=result.cols,
            source_width=result.source_width,
            source_height=result.source_height,
            tile_width=result.tile_width,
            tile_height=result.tile_height,
            aggregate_class=result.aggregate_class,
            aggregate_prediction=result.aggregate_prediction,
            hottest_tile=_tile_to_response(result.hottest_tile),
            tiles=[_tile_to_response(t) for t in result.tiles],
            image_sha256=result.image_sha256,
            total_inference_time_ms=result.total_inference_time_ms,
            timestamp=datetime.now(timezone.utc),
            persisted=persisted,
        ),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=trace,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _tile_to_response(t) -> TileResultResponse:
    return TileResultResponse(
        row=t.row, col=t.col,
        bbox_x=t.bbox_x, bbox_y=t.bbox_y,
        bbox_w=t.bbox_w, bbox_h=t.bbox_h,
        predicted_class=t.predicted_class,
        prediction=t.prediction,
        confidence=t.confidence,
        confidence_band=t.confidence_band,
        top_k=[
            CropTopKEntryResponse(
                class_name=e.class_name, probability=e.probability,
            )
            for e in t.top_k
        ],
    )


async def _persist_tiled(
    session: AsyncSession,
    *,
    tenant_id: str,
    body: CropTiledPredictionRequest,
    result: TiledInferenceResult,
    trace_id: UUID,
) -> UUID:
    """Insert one aggregate row into tenant_<id>.crop_predictions.

    Top-K for the persisted row = the hottest tile's top-K (callers
    drilling into the dashboard see the worst-case forecast). All
    per-tile detail is reconstructable from re-running the analysis
    on the same source image (image_sha256 = stable input_hash).
    """
    prediction_id = uuid4()
    await set_tenant_schema(session, tenant_id)
    hottest = result.hottest_tile
    band = hottest.confidence_band
    top_k_blob = json.dumps(
        [{"class_name": e.class_name, "probability": e.probability}
         for e in hottest.top_k]
    )
    await session.execute(
        text(
            """
            INSERT INTO crop_predictions (
                id, tenant_id,
                model_name, model_version, input_hash,
                prediction, confidence, confidence_band, requires_human_review,
                predicted_class, top_k,
                image_source, image_s3_bucket, image_s3_key, image_sha256,
                location, lga, zone_name,
                inference_time_ms, trace_id, created_at
            ) VALUES (
                :id, :tenant_id,
                :model_name, :model_version, :input_hash,
                :prediction, :confidence, :confidence_band, :requires_human_review,
                :predicted_class, CAST(:top_k AS JSONB),
                'inline', NULL, NULL, :image_sha256,
                CASE WHEN :lon IS NULL OR :lat IS NULL THEN NULL
                     ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                END,
                :lga, :zone_name,
                :inference_time_ms, :trace_id, :created_at
            )
            """
        ),
        {
            "id": prediction_id,
            "tenant_id": tenant_id,
            "model_name": result.model_name,
            "model_version": result.model_version,
            "input_hash": result.image_sha256,
            "prediction": result.aggregate_prediction,
            "confidence": hottest.confidence,
            "confidence_band": band,
            # Tiled mode: always review (operator chose the grid; the
            # aggregate over many tiles is high-uncertainty by design).
            "requires_human_review": True,
            "predicted_class": result.aggregate_class,
            "top_k": top_k_blob,
            "image_sha256": result.image_sha256,
            "lat": body.lat,
            "lon": body.lon,
            "lga": body.lga,
            "zone_name": body.zone_name,
            "inference_time_ms": result.total_inference_time_ms,
            "trace_id": trace_id,
            "created_at": datetime.now(timezone.utc),
        },
    )
    return prediction_id
