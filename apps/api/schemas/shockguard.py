"""Pydantic schemas for Module 05 — ShockGuard (flood + drought)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# What the automated detectors can DETECT — the /scan endpoint's domain.
DetectableShockType = Literal["flood", "drought"]

# What the register can RECORD. ShockGuard is a rainy-season disaster register,
# not a flood log: rainstorms, landslides and gully erosion are real, separately
# reported hazards. Dropping them hides disasters we captured; forcing them into
# 'flood' corrupts the data. They are recorded under their own type instead
# (migration 0036 widens the DB CHECK to match).
ShockEventType = Literal[
    "flood", "drought", "rainstorm", "windstorm", "landslide", "erosion",
]
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

    # Narrow on purpose: only flood + drought have detectors behind them.
    event_type: DetectableShockType
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
    event_type: DetectableShockType
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

    # Set when a 'live' request fell back to the modelled detector because
    # the tenant doesn't yet have enough satellite passes. Null on success.
    # The UI shows this as a gentle info note, never a hard error.
    notice: str | None = None


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
    # Null for ROI-level satellite scans that flag a signal but don't quantify
    # onset / area / population (the on-demand detector + seed do fill these).
    projected_onset_hours: int | None = None
    affected_area_km2: float | None = None
    population_at_risk: int | None = None
    lga: str | None = None
    zone_name: str | None = None
    # Real point geometry when the detector/seed attached one — drives the
    # map marker. Null for events with no geometry (map then synthesises one).
    location: LonLat | None = None
    # Detector rows carry numbers (z_score, backscatter delta dB, NDVI delta).
    # `historical_v1` rows also carry provenance strings/bools — title, source,
    # source_url, event_date, note — so this cannot be dict[str, float]:
    # pydantic coerces per-value and a str raises float_parsing, 500-ing the
    # whole endpoint (production incident 2026-07-26).
    metrics: dict[str, Any] = Field(default_factory=dict)
    source: str
    created_at: datetime


class FeedStatus(BaseModel):
    """Health of ONE detector, reported separately on purpose.

    The panel used to show a single "last scan" taken as the max across all
    detectors. That let a healthy feed mask a silent one: while the SAR scan
    was failing every run, the rainfall scan's success kept the line reading
    "continuously monitored". Per-feed status makes a dead detector visible
    even when its neighbour is fine.
    """

    source: str
    label: str
    # Last run that actually read data. Drives "monitored as of ...".
    last_success_at: datetime | None = None
    # Last run of any outcome — a feed failing daily still has a recent one.
    last_run_at: datetime | None = None
    last_status: str | None = None          # 'succeeded' | 'failed'
    last_error: str | None = None
    active_events: int = 0


class ShockEventListData(BaseModel):
    events: list[ShockEventRow] = Field(default_factory=list)
    # Monitoring status — proves the detector is live even when (correctly)
    # no shock is active. `last_scan_at` is the most recent scheduled scan;
    # `active_shock_count` is how many flood/drought signals that scan is
    # currently flagging (0 = scanned, all clear).
    last_scan_at: datetime | None = None
    active_shock_count: int = 0
    # Per-detector health. Prefer this over last_scan_at in the UI: the
    # aggregate above cannot express "rainfall is current but SAR has been
    # blind for a week", which is the state we were actually in.
    feeds: list[FeedStatus] = Field(default_factory=list)
