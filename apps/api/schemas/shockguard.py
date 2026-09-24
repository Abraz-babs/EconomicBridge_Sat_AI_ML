"""Pydantic schemas for Module 05 — ShockGuard (flood + drought)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.places import NearestPlace


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

    # Nearest named village — ONLY on live satellite detections, whose point is
    # the box the radar/optical signal was measured in. Documented disasters,
    # storms and borrowed state points are area-level and get none.
    nearest_place: NearestPlace | None = None


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


# ─── Storms (Module 05, half-hourly IMERG) ────────────────────────────────
#
# Deliberately NOT folded into ShockEventRow. A storm is a measurement of what
# fell — depth, rate, duration — and a shock event is a claim that something
# went wrong. Merging them would have meant filing storms under event_type
# 'flood', which is precisely the conflation that scored 0 of 11 on the Kebbi
# 2024 backtest. They stay separate types because they are separate claims.


class StormRow(BaseModel):
    """One reconstructed storm over one LGA."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    lga: str
    location: LonLat | None = None

    # UTC. started_at can sit on the previous calendar day from the peak —
    # that is the whole reason this table exists.
    started_at: datetime
    ended_at: datetime
    peak_at: datetime
    # True when a calendar-day total would have split this storm in two. Shown
    # in the UI, because it is the difference between this feed and the daily
    # one and a reader should be able to see it happen.
    crosses_midnight_utc: bool = False

    peak_mm_hr: float
    total_mm: float
    max_1h_mm: float | None = None
    max_3h_mm: float | None = None
    max_6h_mm: float | None = None
    duration_h: float | None = None

    # Where this sat in the LGA's OWN record, and how many days of record that
    # was. Never present the percentile without baseline_days beside it: a 99th
    # percentile over 21 days is not a 99th percentile.
    percentile_1h: float | None = None
    percentile_3h: float | None = None
    baseline_days: int | None = None

    severity: Severity | None = None
    detector_version: str
    detected_at: datetime


class StormMeasurement(BaseModel):
    """The wettest LGAs measured on the most recent scanned day.

    Present so the panel can say "scanned, nothing exceptional" with evidence
    instead of rendering empty and reading as a dead feed. An empty storms list
    with a populated measurement list means the scan ran and found ordinary
    rain — a different state from not having scanned at all.
    """

    lga: str
    day: date
    max_1h_mm: float | None = None
    max_3h_mm: float | None = None
    peak_mm_hr: float | None = None
    # How much of the day was actually observed. IMERG Late occasionally drops
    # slices; a partly-seen day understates every accumulation on it.
    slices_seen: int = 0
    slices_expected: int = 48


class StormListData(BaseModel):
    storms: list[StormRow] = Field(default_factory=list)
    # Wettest LGAs on the most recent day with any measurement.
    measured: list[StormMeasurement] = Field(default_factory=list)
    measured_day: date | None = None
    # LGAs that recorded rain on that day — the scan's actual reach.
    measured_lga_count: int = 0
    # Calendar days of archive held for this tenant. NOT the same quantity as
    # StormRow.baseline_days, which counts the days a given LGA actually
    # recorded rain -- a place gets a row only when something fell there.
    baseline_days: int = 0
    # Places that have accumulated enough of their OWN rain-day history to be
    # ranked, out of every place seen raining at all. In a dry district these
    # diverge for a long time, and a panel reporting only the calendar figure
    # would imply the whole territory was rankable when most of it was not.
    rateable_lgas: int = 0
    known_lgas: int = 0
    min_baseline_days: int = 21
    last_scan_at: datetime | None = None
