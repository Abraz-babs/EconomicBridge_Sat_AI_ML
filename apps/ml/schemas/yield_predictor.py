"""Request + response schemas for POST /api/v1/predict/yield (Slice 04.c)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]


SUPPORTED_CROPS: tuple[str, ...] = (
    "maize", "rice", "cassava", "yam", "sorghum", "millet", "cowpea",
    "groundnut", "soybean", "tomato", "pepper", "onion", "plantain",
    "sweet_potato",
)


class YieldPredictionRequest(BaseModel):
    """Body of POST /api/v1/predict/yield.

    All eight features required by the Random Forest regressor. The
    tenant_id + crop combination scopes the prediction to one ROI ×
    one staple; the dashboard typically fires 14 requests in parallel
    when building a tenant-wide yield forecast.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=50)
    crop: str = Field(min_length=1, max_length=40)

    # Vegetation health — last 30 days
    ndvi_mean_30d: Annotated[float, Field(ge=0, le=1)]
    ndvi_anomaly: Annotated[float, Field(ge=-1, le=1)]

    # Weather — last 30 days, cumulative or anomaly vs seasonal mean
    rainfall_30d_mm: Annotated[float, Field(ge=0, le=2000)]
    rainfall_anomaly: Annotated[float, Field(ge=-1, le=1)]

    # Soil quality proxy from organic matter + texture composite (0..1)
    soil_quality_index: Annotated[float, Field(ge=0, le=1)]

    # Historical yield mean for THIS crop in THIS region (tons/ha)
    historical_yield_mean_t_ha: Annotated[float, Field(ge=0, le=15)]

    # Days remaining until typical harvest window (0..200; informs
    # the model how much can still go wrong)
    days_to_harvest: Annotated[int, Field(ge=0, le=365)]

    # Optional spatial context — stored if provided
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)

    persist: bool = True


class YieldPredictionData(BaseModel):
    """Body of the SuccessResponse[T] returned by predict_yield()."""

    prediction_id: UUID | None

    model_name: str
    model_version: str
    tenant_id: str
    crop: str

    # Canonical 0..1 score: predicted yield / crop's reference max.
    # 1.0 = best-case yield for this crop/region; 0.0 = total failure.
    prediction: float
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool

    # The semantic answer the dashboard renders.
    predicted_yield_t_ha: float
    # 80% prediction interval from RF tree variance. None when the
    # model couldn't estimate one (rare; e.g., new geography).
    yield_pi_low_t_ha: float | None
    yield_pi_high_t_ha: float | None

    shap_values: dict[str, float]
    shap_base_value: float | None
    input_hash: str
    inference_time_ms: int
    timestamp: datetime
    persisted: bool
