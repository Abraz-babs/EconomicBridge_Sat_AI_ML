"""HTTP client for the ML conflict predictor.

The ml service runs separately (port 8002 in dev, dedicated ECS service
in prod). The contract is `POST /api/v1/predict/conflict` returning the
SuccessResponse envelope from apps/ml/schemas/envelope.py. We unwrap it
into a flat MLConflictPrediction dataclass for callers in this service.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MLConflictPrediction:
    """Flat projection of the ML response we actually use downstream."""

    prediction: float            # 0..1 conflict probability
    confidence: float            # 0..1 — same as prediction for binary RF
    confidence_band: str         # HIGH | MEDIUM | LOW
    requires_human_review: bool
    model_name: str
    model_version: str
    input_hash: str              # ML's SHA-256 of the feature vector
    shap_values: dict[str, float]
    shap_base_value: float | None
    inference_time_ms: int
    persisted: bool              # True iff ml.persist=True and DB write OK


class MLError(RuntimeError):
    """Non-200 from ML or malformed body."""


async def predict_conflict(
    *,
    tenant_id: str,
    heat_signature_intensity: float,
    boundary_distance_km: float,
    ndvi_delta: float,
    herder_density: float,
    historical_incidents: int,
    rainfall_anomaly: float,
    is_new_geography: bool,
    lat: float | None = None,
    lon: float | None = None,
    lga: str | None = None,
    zone_name: str | None = None,
    persist: bool = True,
    http: httpx.AsyncClient | None = None,
) -> MLConflictPrediction:
    """Call POST /predict/conflict and parse the envelope."""
    settings = get_settings()
    body = {
        "tenant_id": tenant_id,
        "heat_signature_intensity": heat_signature_intensity,
        "boundary_distance_km": boundary_distance_km,
        "ndvi_delta": ndvi_delta,
        "herder_density": herder_density,
        "historical_incidents": historical_incidents,
        "rainfall_anomaly": rainfall_anomaly,
        "is_new_geography": is_new_geography,
        "persist": persist,
    }
    if lat is not None:
        body["lat"] = lat
    if lon is not None:
        body["lon"] = lon
    if lga is not None:
        body["lga"] = lga
    if zone_name is not None:
        body["zone_name"] = zone_name

    url = f"{settings.ml_base_url}/predict/conflict"
    own_client = http is None
    client = http if http is not None else httpx.AsyncClient()
    try:
        resp = await client.post(url, json=body, timeout=30.0)
    finally:
        if own_client:
            await client.aclose()

    if resp.status_code != 200:
        raise MLError(f"ML predict/conflict {resp.status_code}: {resp.text[:200]}")

    try:
        envelope = resp.json()
    except ValueError as exc:
        raise MLError(f"ML predict/conflict: non-JSON body: {resp.text[:200]}") from exc

    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        raise MLError(f"ML predict/conflict: missing data block: {envelope}")

    try:
        return MLConflictPrediction(
            prediction=float(data["prediction"]),
            confidence=float(data["confidence"]),
            confidence_band=str(data["confidence_band"]),
            requires_human_review=bool(data["requires_human_review"]),
            model_name=str(data["model_name"]),
            model_version=str(data["model_version"]),
            input_hash=str(data["input_hash"]),
            shap_values=dict(data.get("shap_values") or {}),
            shap_base_value=(
                float(data["shap_base_value"])
                if data.get("shap_base_value") is not None
                else None
            ),
            inference_time_ms=int(data["inference_time_ms"]),
            persisted=bool(data.get("persisted", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MLError(f"ML predict/conflict: malformed data: {data}") from exc
