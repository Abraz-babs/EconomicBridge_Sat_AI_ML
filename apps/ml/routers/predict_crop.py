"""POST /api/v1/predict/crop_disease — ResNet-50 crop disease classifier.

Mirrors the predict_conflict pipeline (CLAUDE.md §9): validate, run model,
optionally persist to tenant_<id>.crop_predictions, return the standard
envelope. Inline base64 only in Slice 5a; S3 fetch arrives in Slice 5c.
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
from models.crop_classifier import (
    CropPredictionInput,
    CropTopKEntry,
    get_classifier,
    hash_image_bytes,
)
from schemas.crop import (
    CropPredictionData,
    CropPredictionRequest,
    CropTopKEntryResponse,
)
from schemas.envelope import ResponseMeta, SuccessResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/crop_disease",
    response_model=SuccessResponse[CropPredictionData],
    summary="Run the ResNet-50 crop disease classifier on one image",
)
async def predict_crop_disease(
    body: CropPredictionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[CropPredictionData]:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )

    image_bytes, image_source = _resolve_image_bytes(body)
    image_sha = hash_image_bytes(image_bytes)
    classifier_input = CropPredictionInput(
        image_bytes=image_bytes,
        image_sha256=image_sha,
        image_source=image_source,
        image_s3_bucket=body.image_s3_bucket,
        image_s3_key=body.image_s3_key,
    )

    classifier = get_classifier()
    trace = _trace_id(request)
    try:
        result, top_k = classifier.predict(
            tenant_id=tenant_id,
            image=classifier_input,
            top_k=body.top_k,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    saliency_b64: str | None = None
    if body.compute_saliency:
        # Failure surfaces internally as None — never block the prediction
        # on an explainability hiccup (CLAUDE.md §4.4).
        saliency_b64 = classifier.compute_saliency(classifier_input.image_bytes)

    prediction_id: UUID | None = None
    persisted = False
    if body.persist:
        prediction_id = await _persist_crop_prediction(
            session,
            tenant_id=tenant_id,
            body=body,
            result=result,
            image=classifier_input,
            top_k=top_k,
            trace_id=trace,
        )
        persisted = prediction_id is not None

    return SuccessResponse(
        data=CropPredictionData(
            prediction_id=prediction_id,
            model_name=result.model_name,
            model_version=result.model_version,
            tenant_id=result.tenant_id,
            predicted_class=result.features["predicted_class"],
            prediction=result.prediction,
            confidence=result.confidence,
            confidence_band=result.confidence_band,
            requires_human_review=result.requires_human_review,
            top_k=[
                CropTopKEntryResponse(
                    class_name=e.class_name, probability=e.probability
                )
                for e in top_k
            ],
            image_source=classifier_input.image_source,
            image_s3_bucket=classifier_input.image_s3_bucket,
            image_s3_key=classifier_input.image_s3_key,
            image_sha256=image_sha,
            saliency_b64=saliency_b64,
            input_hash=result.input_hash,
            inference_time_ms=result.inference_time_ms,
            timestamp=result.timestamp,
            persisted=persisted,
        ),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=trace,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _resolve_image_bytes(
    body: CropPredictionRequest,
) -> tuple[bytes, str]:
    if body.image_base64 is not None:
        return base64.b64decode(body.image_base64, validate=True), "inline"
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "S3-keyed image fetch is not wired yet (arrives with Slice 5c). "
            "For now, submit images inline via `image_base64`."
        ),
    )


async def _persist_crop_prediction(
    session: AsyncSession,
    *,
    tenant_id: str,
    body: CropPredictionRequest,
    result,
    image: CropPredictionInput,
    top_k: list[CropTopKEntry],
    trace_id: UUID,
) -> UUID:
    """Insert into tenant_<id>.crop_predictions. Returns the new row id."""
    prediction_id = uuid4()
    await set_tenant_schema(session, tenant_id)
    top_k_blob = json.dumps(
        [{"class_name": e.class_name, "probability": e.probability}
         for e in top_k]
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
                :image_source, :image_s3_bucket, :image_s3_key, :image_sha256,
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
            "input_hash": result.input_hash,
            "prediction": result.prediction,
            "confidence": result.confidence,
            "confidence_band": result.confidence_band,
            "requires_human_review": result.requires_human_review,
            "predicted_class": result.features["predicted_class"],
            "top_k": top_k_blob,
            "image_source": image.image_source,
            "image_s3_bucket": image.image_s3_bucket,
            "image_s3_key": image.image_s3_key,
            "image_sha256": image.image_sha256,
            "lat": body.lat,
            "lon": body.lon,
            "lga": body.lga,
            "zone_name": body.zone_name,
            "inference_time_ms": result.inference_time_ms,
            "trace_id": trace_id,
            "created_at": result.timestamp,
        },
    )
    return prediction_id
