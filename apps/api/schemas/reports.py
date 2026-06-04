"""Schemas for the reports endpoints (generic across modules)."""
from __future__ import annotations

from pydantic import BaseModel


class ReportMetric(BaseModel):
    label: str
    display: str


class ReportBreakdownRow(BaseModel):
    key: str
    count: int


class ReportBreakdown(BaseModel):
    title: str
    rows: list[ReportBreakdownRow]


class ReportSummary(BaseModel):
    module: str
    label: str
    date_from: str
    date_to: str
    total_rows: int
    metrics: list[ReportMetric]
    breakdown: ReportBreakdown | None = None


class ReportModuleInfo(BaseModel):
    """A reportable module (for the frontend's module picker)."""
    key: str
    label: str


# ─── Scheduled report subscriptions (super-admin) ─────────────────────────

from datetime import datetime  # noqa: E402
from uuid import UUID  # noqa: E402

from pydantic import EmailStr, Field  # noqa: E402


class ReportSubscription(BaseModel):
    id: UUID
    tenant_id: str
    module: str
    frequency: str
    recipient_email: str
    enabled: bool
    last_sent_at: datetime | None = None
    created_at: datetime | None = None


class ReportSubscriptionCreate(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    module: str
    frequency: str = Field(pattern=r"^(monthly|quarterly)$")
    recipient_email: EmailStr
