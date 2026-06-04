"""Schemas for the reports endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class ReportSummary(BaseModel):
    tenant_id: str
    date_from: str
    date_to: str
    total_alerts: int
    live_alerts: int
    seed_alerts: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    resolved: int
    affected_area_ha: float
    livelihoods_at_risk: int
    economic_value_ngn: float
