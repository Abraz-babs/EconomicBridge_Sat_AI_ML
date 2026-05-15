"""Request + response schemas for POST /api/v1/predict/conflict."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConflictPredictionRequest(BaseModel):
    """Body of POST /api/v1/predict/conflict.

    All seven features required by the Random Forest. `tenant_id` is the
    pilot slug ("kebbi", etc.) — validated against the allowlist in
    db.is_valid_tenant_id before the request reaches the model.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=50)

    heat_signature_intensity: Annotated[float, Field(ge=0, le=1)]
    boundary_distance_km: Annotated[float, Field(ge=0, le=200)]
    ndvi_delta: Annotated[float, Field(ge=-1, le=1)]
    herder_density: Annotated[float, Field(ge=0, le=1)]
    historical_incidents: Annotated[int, Field(ge=0, le=1000)]
    rainfall_anomaly: Annotated[float, Field(ge=-1, le=1)]
    is_new_geography: bool = False

    # Optional spatial context — stored if provided, useful when the
    # prediction is later joined with map layers.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)
    related_alert_id: UUID | None = None

    # Caller controls persistence (e.g., dry-run during model evaluation).
    persist: bool = True


class ConflictPredictionData(BaseModel):
    """Body of the SuccessResponse[T] returned by predict()."""

    prediction_id: UUID | None
    model_name: str
    model_version: str
    tenant_id: str

    prediction: float
    confidence: float
    confidence_band: str            # HIGH | MEDIUM | LOW
    requires_human_review: bool

    shap_values: dict[str, float]
    shap_base_value: float | None
    input_hash: str
    inference_time_ms: int
    timestamp: datetime
    persisted: bool
