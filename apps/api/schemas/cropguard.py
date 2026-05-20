"""Pydantic schemas for the CropGuard list endpoint.

Mirrors the persisted shape of `tenant_<id>.crop_predictions` (migration
0014). The API service is a read-only consumer of this table — writes
happen via the ML service (`apps/ml`, port 8002).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]
ImageSource = Literal["s3", "inline"]


class CropTopKEntry(BaseModel):
    class_name: str
    probability: float


class CropPredictionRow(BaseModel):
    """One row from `tenant_<id>.crop_predictions`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str

    predicted_class: str
    prediction: float
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool

    top_k: list[CropTopKEntry]

    image_source: ImageSource
    image_s3_key: str | None
    image_s3_bucket: str | None

    model_name: str
    model_version: str
    inference_time_ms: int | None

    created_at: datetime


class CropPredictionListData(BaseModel):
    predictions: list[CropPredictionRow] = Field(default_factory=list)
