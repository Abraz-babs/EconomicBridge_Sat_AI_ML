"""Pydantic schemas for the Farmland Protection module.

Public-facing types only. SQLAlchemy ORM rows never cross the router boundary
(CLAUDE.md §13) — services map AlertEvent → AlertResponse here.

The closed-set enums mirror the CHECK constraints on alert_events (see
migration 0003). Drift between them would be a bug — keep them in sync.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AlertType(str, Enum):
    CONFLICT = "conflict"
    FLOOD = "flood"
    CROP_DISEASE = "crop_disease"
    DROUGHT = "drought"
    FIRE = "fire"  # NASA FIRMS-derived; added in migration 0011


class LonLat(BaseModel):
    """A WGS84 point. Wraps PostGIS POINT to a client-friendly shape."""

    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class AlertResponse(BaseModel):
    """A single alert as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus

    zone_name: str | None
    lga: str | None
    location: LonLat | None

    confidence_score: float | None = Field(default=None, ge=0, le=1)
    affected_area_ha: float | None = None
    livelihoods_at_risk: int | None = None
    economic_value_ngn: float | None = None
    predicted_breach_hours: int | None = None

    satellite_source: str | None
    satellite_pass_time: AwareDatetime | None
    model_name: str | None
    model_version: str | None
    human_review_required: bool
    agencies_notified: list[str] | None

    created_at: AwareDatetime
    updated_at: AwareDatetime


class AlertListData(BaseModel):
    """Payload of SuccessResponse[AlertListData] for GET /farmland/alerts."""

    alerts: list[AlertResponse]


class AlertStatusPatch(BaseModel):
    """Request body for PATCH /farmland/alerts/{id} — lifecycle transitions only."""

    model_config = ConfigDict(extra="forbid")

    status: AlertStatus


# ─── Query parameter validation ────────────────────────────────────────────


# Each "list" filter accepts a single value or repeats: ?severity=critical&severity=high
class AlertListQuery(BaseModel):
    """Validated query parameters for GET /api/v1/farmland/alerts."""

    model_config = ConfigDict(extra="forbid")

    page: Annotated[int, Field(ge=1, le=10_000)] = 1
    per_page: Annotated[int, Field(ge=1, le=100)] = 20

    severity: list[AlertSeverity] | None = None
    status: list[AlertStatus] | None = None
    alert_type: list[AlertType] | None = None
    lga: str | None = Field(default=None, max_length=120)
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None

    include_deleted: bool = False

    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def limit(self) -> int:
        return self.per_page
