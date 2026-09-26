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


class LastAdvisory(BaseModel):
    """The most recent farmer rainfall advisory that reached anyone.

    Aggregate only: when, where (LGA) and how many recipients. Never a name
    or a number — the front page reads this.
    """
    sent_at: datetime
    region: str
    lga: str
    recipients: int


class OverviewStatsData(BaseModel):
    tenants_live: int
    lgas_mapped: int
    settlements_scored: int
    crop_detections: int
    satellite_observations: int
    live_sources: list[str]
    cards: list[OverviewStatCard]
    generated_at: datetime
    # Front-page figures that move with each scan or send (defaults keep older
    # clients and tests valid).
    farmland_greened_ha: float = 0.0     # crops + rangeland, latest season
    land_changes: int = 0                # live land_change_v1 detections
    sms_subscribers: int = 0             # active SMS subscribers (count only)
    advisories_sent: int = 0             # rainfall advisories that reached >= 1 person
    last_advisory: LastAdvisory | None = None


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
