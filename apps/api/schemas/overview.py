"""Schema for GET /api/v1/overview/stats — the real platform-overview KPIs.

These are live roll-ups across every pilot tenant schema, so the dashboard
overview shows what the feeds actually hold rather than hard-coded figures.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OverviewStatCard(BaseModel):
    """One KPI card: a real value plus an honest, non-fabricated subtitle."""

    label: str
    value: str
    subtitle: str
    tone: str  # "ok" | "warn" | "neg" | "" — drives the delta colour


class OverviewStatsData(BaseModel):
    tenants_live: int
    lgas_mapped: int
    settlements_scored: int
    crop_detections: int
    satellite_observations: int
    live_sources: list[str]
    cards: list[OverviewStatCard]
    generated_at: datetime


class CropHealthRow(BaseModel):
    label: str   # e.g. "Maize — Benue"
    pct: int     # % of detections classified healthy
    tone: str    # "ok" | "warn" | "neg"


class CropHealthData(BaseModel):
    rows: list[CropHealthRow]
    generated_at: datetime


class ActiveResponseRow(BaseModel):
    region: str   # e.g. "Benue — Flood"
    sub: str      # e.g. "Logo · high"
    status: str   # ACTIVE | WATCH | MONITOR | RECOVERY
    tone: str     # css status class suffix


class ActiveResponseData(BaseModel):
    rows: list[ActiveResponseRow]
    generated_at: datetime
