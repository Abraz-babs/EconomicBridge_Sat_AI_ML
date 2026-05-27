"""POST /api/v1/predict/conflict — Random Forest conflict predictor.

(Crop disease classifier lives in routers/predict_crop.py — same prefix,
separate file to keep each model's persistence path readable on its own.)

Pipeline:
  1. Validate the request body (Pydantic).
  2. Validate tenant_id against the allowlist (404 if unknown).
  3. Run the Random Forest predictor → ModelPrediction (CLAUDE.md §9).
  4. If `persist=True`, INSERT one row into tenant_<id>.conflict_predictions.
  5. Return the standard SuccessResponse[ConflictPredictionData] envelope.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id, set_tenant_schema
from models.conflict_predictor import ConflictFeatures, get_predictor
from schemas.conflict import ConflictPredictionData, ConflictPredictionRequest
from schemas.envelope import ResponseMeta, SuccessResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/conflict",
    response_model=SuccessResponse[ConflictPredictionData],
    summary="Run the conflict Random Forest for one feature vector",
)
async def predict_conflict(
    body: ConflictPredictionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ConflictPredictionData]:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )

    features = ConflictFeatures(
        heat_signature_intensity=body.heat_signature_intensity,
        boundary_distance_km=body.boundary_distance_km,
        ndvi_delta=body.ndvi_delta,
        herder_density=body.herder_density,
        historical_incidents=body.historical_incidents,
        rainfall_anomaly=body.rainfall_anomaly,
        is_new_geography=body.is_new_geography,
    )

    predictor = get_predictor()
    trace = _trace_id(request)
    try:
        result = predictor.predict(tenant_id=tenant_id, features=features)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    prediction_id: UUID | None = None
    persisted = False
    if body.persist:
        prediction_id = await _persist_prediction(
            session,
            tenant_id=tenant_id,
            body=body,
            result=result,
            trace_id=trace,
        )
        persisted = prediction_id is not None

    return SuccessResponse(
        data=ConflictPredictionData(
            prediction_id=prediction_id,
            model_name=result.model_name,
            model_version=result.model_version,
            tenant_id=result.tenant_id,
            prediction=result.prediction,
            confidence=result.confidence,
            confidence_band=result.confidence_band,
            requires_human_review=result.requires_human_review,
            shap_values=result.shap_values,
            shap_base_value=result.shap_base_value,
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


async def _persist_prediction(
    session: AsyncSession,
    *,
    tenant_id: str,
    body: ConflictPredictionRequest,
    result,
    trace_id: UUID,
) -> UUID:
    """Insert into tenant_<id>.conflict_predictions. Returns the new row id."""
    prediction_id = uuid4()
    await set_tenant_schema(session, tenant_id)
    await session.execute(
        text(
            """
            INSERT INTO conflict_predictions (
                id, tenant_id,
                model_name, model_version, input_hash,
                prediction, confidence, confidence_band, requires_human_review,
                features, shap_values, shap_base_value,
                location, lga, zone_name,
                related_alert_id,
                inference_time_ms, trace_id, created_at
            ) VALUES (
                :id, :tenant_id,
                :model_name, :model_version, :input_hash,
                :prediction, :confidence, :confidence_band, :requires_human_review,
                CAST(:features AS JSONB), CAST(:shap_values AS JSONB), :shap_base_value,
                -- Explicit CASTs on every nullable param so asyncpg /
                -- Postgres can parse the statement when one of these
                -- arrives as NULL. Without the casts asyncpg raises
                -- "could not determine data type of parameter" — Slice 10
                -- worked around by setting persist=False on every call
                -- from the conflict_pipeline; Slice 12 closes the gap.
                CASE WHEN CAST(:lon AS DOUBLE PRECISION) IS NULL
                       OR CAST(:lat AS DOUBLE PRECISION) IS NULL THEN NULL
                     ELSE ST_SetSRID(
                       ST_MakePoint(
                         CAST(:lon AS DOUBLE PRECISION),
                         CAST(:lat AS DOUBLE PRECISION)
                       ), 4326)
                END,
                CAST(:lga AS TEXT), CAST(:zone_name AS TEXT),
                CAST(:related_alert_id AS UUID),
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
            "features": json.dumps(result.features),
            "shap_values": json.dumps(result.shap_values),
            "shap_base_value": result.shap_base_value,
            "lat": body.lat,
            "lon": body.lon,
            "lga": body.lga,
            "zone_name": body.zone_name,
            "related_alert_id": body.related_alert_id,
            "inference_time_ms": result.inference_time_ms,
            "trace_id": trace_id,
            "created_at": result.timestamp,
        },
    )
    return prediction_id
