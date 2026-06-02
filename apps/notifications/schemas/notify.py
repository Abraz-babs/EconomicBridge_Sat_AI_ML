"""Pydantic schemas for notify + subscriber endpoints.

Closed enums mirror the CHECK constraints on the DB tables — keep in sync
with apps/api/migrations/versions/0006_create_sms_outbox_and_subscribers.py.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Closed-set enums (match DB CHECK constraints) ────────────────────────


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertType(str, Enum):
    CONFLICT = "conflict"
    FLOOD = "flood"
    CROP_DISEASE = "crop_disease"
    DROUGHT = "drought"


class Language(str, Enum):
    EN = "en"
    FR = "fr"
    PT = "pt"
    HA = "ha"  # Hausa
    YO = "yo"  # Yoruba
    IG = "ig"  # Igbo


class Channel(str, Enum):
    SMS = "sms"
    VOICE = "voice"
    WHATSAPP = "whatsapp"


class SeverityThreshold(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    ALL = "all"


# ─── Subscribers ──────────────────────────────────────────────────────────


class SubscriberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)
    # E.164 — international phone with leading + and 7..15 digits.
    phone_e164: str = Field(pattern=r"^\+[1-9][0-9]{6,15}$")
    language: Language = Language.EN
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)
    severity_threshold: SeverityThreshold = SeverityThreshold.HIGH
    alert_types: list[AlertType] | None = None
    channel: Channel = Channel.SMS


class SubscriberResponse(BaseModel):
    id: UUID
    tenant_id: str
    full_name: str | None
    phone_e164: str
    language: str
    lga: str | None
    zone_name: str | None
    severity_threshold: str
    alert_types: list[str] | None
    channel: str
    is_active: bool
    opted_in_at: datetime
    opted_out_at: datetime | None


class SubscriberListData(BaseModel):
    subscribers: list[SubscriberResponse]


# ─── Notify (dispatch) ────────────────────────────────────────────────────


class NotifyConflictRequest(BaseModel):
    """Trigger SMS dispatches for one conflict prediction or alert.

    At least one of prediction_id / alert_id should be set so the outbox can
    record the source. When neither is set, the dispatch is treated as ad-hoc
    (idempotency disabled — same recipient may receive again).
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=50)
    severity: Severity
    confidence_band: str | None = Field(default=None, max_length=10)
    alert_type: AlertType = AlertType.CONFLICT
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)
    affected_area_ha: float | None = None
    livelihoods_at_risk: int | None = None
    eta_hours: int | None = Field(default=None, ge=0, le=240)
    prediction_id: UUID | None = None
    alert_id: UUID | None = None


class DispatchSummary(BaseModel):
    """Per-subscriber outcome inside the response."""

    subscriber_id: UUID
    phone_e164: str
    provider: str
    status: str
    provider_message_id: str | None
    error_message: str | None


class NotifyConflictData(BaseModel):
    tenant_id: str
    severity: str
    matched_subscribers: int
    dispatched: int
    skipped_duplicate: int
    failed: int
    provider_chosen: str
    rendered_message: str
    dispatches: list[DispatchSummary]


class SmsPreviewData(BaseModel):
    """Rendered SMS preview for one language — no send, no PII, no DB."""
    language: str
    verified: bool   # False for DRAFT languages pending native review
    body: str
    chars: int
