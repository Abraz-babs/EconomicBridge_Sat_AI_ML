"""Pydantic schemas for Module 05 — ShockGuard (flood + drought)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ShockEventType = Literal["flood", "drought"]
Severity = Literal["low", "medium", "high", "critical"]
ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]


# ─── Series points (for the chart) ────────────────────────────────────────


class FloodSeriesPoint(BaseModel):
    observed_at: datetime
    backscatter_db: float


class DroughtSeriesPoint(BaseModel):
    observed_at: datetime
    lst_anomaly_c: float
    ndvi_anomaly: float
    stress_index: float


# ─── Scan request ─────────────────────────────────────────────────────────


DataSource = Literal["synthetic", "live"]


class ShockScanRequest(BaseModel):
    """Body of POST /api/v1/shockguard/scan."""

    model_config = ConfigDict(extra="forbid")

    event_type: ShockEventType
    # Demo mode: inject a synthetic anomaly so the dashboard shows
    # a clear positive event for walkthroughs/screenshots.
    demo_inject_anomaly: bool = False
    persist: bool = True
    # Where the SAR/NDVI series comes from:
    #   'synthetic' (default) — deterministic per-tenant series. Useful
    #     for demos + tests, never makes a CDSE call.
    #   'live' — reads real Sentinel-1 / Sentinel-2 rows from
    #     tenant_<id>.satellite_observations (populated by the ingestion
    #     service's scheduled run). Drought stays synthetic until MODIS
    #     LST ingestion lands in Phase B.
    data_source: DataSource = "synthetic"


# ─── Scan result ──────────────────────────────────────────────────────────


class ShockScanData(BaseModel):
    event_id: UUID | None
    tenant_id: str
    event_type: ShockEventType
    detector_name: str
    detector_version: str

    severity: Severity
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool
    triggered: bool

    projected_onset_hours: int
    affected_area_km2: float
    population_at_risk: int

    metrics: dict[str, float]
    flood_series: list[FloodSeriesPoint] = Field(default_factory=list)
    drought_series: list[DroughtSeriesPoint] = Field(default_factory=list)

    persisted: bool


# ─── List endpoint ────────────────────────────────────────────────────────


class LonLat(BaseModel):
    lon: float
    lat: float


class ShockEventRow(BaseModel):
    """One row from `tenant_<id>.shock_events`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    event_type: ShockEventType
    detector_name: str
    detector_version: str
    severity: Severity
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool
    projected_onset_hours: int
    affected_area_km2: float
    population_at_risk: int
    lga: str | None = None
    zone_name: str | None = None
    # Real point geometry when the detector/seed attached one — drives the
    # map marker. Null for events with no geometry (map then synthesises one).
    location: LonLat | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    source: str
    created_at: datetime


class ShockEventListData(BaseModel):
    events: list[ShockEventRow] = Field(default_factory=list)
