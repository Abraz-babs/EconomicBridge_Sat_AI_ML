"""Pydantic schemas for the unified intelligence feed."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FeedKind = Literal[
    "alert_event", "ndvi_anomaly", "shock_event",
    "aid_coverage", "poverty_village",
]
FeedTag = Literal["Disaster", "Agriculture", "Poverty", "Aid", "Encroachment"]
FeedSeverity = Literal["low", "medium", "high", "critical"]


class FeedEventModel(BaseModel):
    """One normalized event in the intelligence feed."""

    model_config = ConfigDict(from_attributes=True)

    kind: FeedKind
    tenant_id: str
    title: str
    region: str | None = None
    tag: FeedTag
    severity: FeedSeverity
    source: str
    observed_at: datetime


class IntelligenceFeedData(BaseModel):
    """Body of the SuccessResponse[T] returned by GET /intelligence/feed."""

    events: list[FeedEventModel] = Field(default_factory=list)
    total: int = 0
