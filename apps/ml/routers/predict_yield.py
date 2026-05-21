"""POST /api/v1/predict/yield — Random Forest yield-prediction endpoint (Slice 04.c).

Mirrors the conflict-predictor pipeline (CLAUDE.md §9):
  1. Validate request body (Pydantic).
  2. Validate tenant_id against the allowlist.
  3. Run YieldPredictor → ModelPrediction + raw yield + PI.
  4. If persist=True, INSERT one row into tenant_<id>.yield_predictions.
  5. Return the standard SuccessResponse[YieldPredictionData] envelope.
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
from models.yield_predictor import YieldFeatures, get_predictor
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.yield_predictor import (
    SUPPORTED_CROPS,
    YieldPredictionData,
    YieldPredictionRequest,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/yield",
    response_model=SuccessResponse[YieldPredictionData],
    summary="Run the yield Random Forest for one feature vector",
)
async def predict_yield(
    body: YieldPredictionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[YieldPredictionData]:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )
    crop = body.crop.strip().lower()
    if crop not in SUPPORTED_CROPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported crop: {crop!r}. "
                f"Valid: {sorted(SUPPORTED_CROPS)}"
            ),
        )

    features = YieldFeatures(
        crop=crop,
        ndvi_mean_30d=body.ndvi_mean_30d,
        ndvi_anomaly=body.ndvi_anomaly,
        rainfall_30d_mm=body.rainfall_30d_mm,
        rainfall_anomaly=body.rainfall_anomaly,
        soil_quality_index=body.soil_quality_index,
        historical_yield_mean_t_ha=body.historical_yield_mean_t_ha,
        days_to_harvest=body.days_to_harvest,
    )

    predictor = get_predictor()
    trace = _trace_id(request)
    try:
        result, yield_t_ha, pi_low, pi_high = predictor.predict(
            tenant_id=tenant_id, features=features,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    prediction_id: UUID | None = None
    persisted = False
    if body.persist:
        prediction_id = await _persist_prediction(
            session,
            tenant_id=tenant_id, body=body, result=result,
            yield_t_ha=yield_t_ha, pi_low=pi_low, pi_high=pi_high,
            trace_id=trace,
        )
        persisted = prediction_id is not None

    return SuccessResponse(
        data=YieldPredictionData(
            prediction_id=prediction_id,
            model_name=result.model_name,
            model_version=result.model_version,
            tenant_id=result.tenant_id,
            crop=crop,
            prediction=result.prediction,
            confidence=result.confidence,
            confidence_band=result.confidence_band,
            requires_human_review=result.requires_human_review,
            predicted_yield_t_ha=yield_t_ha,
            yield_pi_low_t_ha=pi_low,
            yield_pi_high_t_ha=pi_high,
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
    body: YieldPredictionRequest,
    result,
    yield_t_ha: float,
    pi_low: float | None,
    pi_high: float | None,
    trace_id: UUID,
) -> UUID:
    prediction_id = uuid4()
    await set_tenant_schema(session, tenant_id)
    await session.execute(
        text(
            """
            INSERT INTO yield_predictions (
                id, tenant_id,
                model_name, model_version, input_hash,
                prediction, confidence, confidence_band, requires_human_review,
                crop, predicted_yield_t_ha, yield_pi_low_t_ha, yield_pi_high_t_ha,
                features, shap_values, shap_base_value,
                location, lga, zone_name,
                inference_time_ms, trace_id, created_at
            ) VALUES (
                :id, :tenant_id,
                :model_name, :model_version, :input_hash,
                :prediction, :confidence, :confidence_band, :requires_human_review,
                :crop, :yield_t_ha, :pi_low, :pi_high,
                CAST(:features AS JSONB), CAST(:shap_values AS JSONB), :shap_base_value,
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
            "crop": body.crop.strip().lower(),
            "yield_t_ha": yield_t_ha,
            "pi_low": pi_low,
            "pi_high": pi_high,
            "features": json.dumps(result.features),
            "shap_values": json.dumps(result.shap_values),
            "shap_base_value": result.shap_base_value,
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
