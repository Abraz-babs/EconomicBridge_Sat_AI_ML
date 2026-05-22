"""Pydantic schemas for the CropGuard list endpoint.

Mirrors the persisted shape of `tenant_<id>.crop_predictions` (migration
0014). The API service is a read-only consumer of this table — writes
happen via the ML service (`apps/ml`, port 8002).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]
ImageSource = Literal["s3", "inline"]


class CropTopKEntry(BaseModel):
    class_name: str
    probability: float


class CropPredictionRow(BaseModel):
    """One row from `tenant_<id>.crop_predictions`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str

    predicted_class: str
    prediction: float
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool

    top_k: list[CropTopKEntry]

    image_source: ImageSource
    image_s3_key: str | None
    image_s3_bucket: str | None

    model_name: str
    model_version: str
    inference_time_ms: int | None

    created_at: datetime


class CropPredictionListData(BaseModel):
    predictions: list[CropPredictionRow] = Field(default_factory=list)


# ─── Market price intelligence (Slice 04.b) ───────────────────────────────


class CropPricePoint(BaseModel):
    """One (crop, region, month) observation from public.crop_prices."""

    crop: str
    region: str
    observed_at: datetime
    price_ngn_per_kg: float
    source: str


class CropPriceSeriesData(BaseModel):
    """Time-series view: one crop, the requested region, last N months."""

    crop: str
    region: str
    months: int
    points: list[CropPricePoint] = Field(default_factory=list)
    latest_price: float | None = None
    earliest_price: float | None = None
    pct_change: float | None = None    # latest vs earliest, signed
    sources: list[str] = Field(default_factory=list)


class CropPriceCorrelationData(BaseModel):
    """Correlation matrix: every crop × every crop, Pearson on
    monthly log-returns. Symmetric; diagonal is always 1.0."""

    region: str
    months: int
    crops: list[str] = Field(default_factory=list)
    # Square matrix len(crops) × len(crops). matrix[i][j] = corr(crops[i], crops[j]).
    matrix: list[list[float]] = Field(default_factory=list)


# ─── Yield forecasts (Slice 04.c) ─────────────────────────────────────────


class YieldForecastRow(BaseModel):
    """One row from `tenant_<id>.yield_predictions`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    crop: str

    prediction: float
    confidence: float
    confidence_band: ConfidenceBand
    requires_human_review: bool

    predicted_yield_t_ha: float
    yield_pi_low_t_ha: float | None
    yield_pi_high_t_ha: float | None

    model_name: str
    model_version: str
    inference_time_ms: int | None

    created_at: datetime


class YieldForecastListData(BaseModel):
    forecasts: list[YieldForecastRow] = Field(default_factory=list)


# ─── NDVI anomaly detection (Slice 04.d) ─────────────────────────────────


class NdviSamplePoint(BaseModel):
    observed_at: datetime
    ndvi: float


NdviDataSource = Literal["synthetic", "live"]


class NdviScanRequest(BaseModel):
    """Body of POST /api/v1/cropguard/ndvi/scan."""

    model_config = ConfigDict(extra="forbid")

    # Optional crop hint — surfaced in the persisted row, doesn't
    # affect detection (algorithm is canopy-level NDVI, crop-agnostic).
    crop: str | None = Field(default=None, max_length=40)
    # When true, demo path: inject a synthetic 18% NDVI drop into the
    # last 14 days so the dashboard renders a clear anomaly. Useful
    # for screenshots + walkthroughs.
    demo_inject_anomaly: bool = False
    # Persist the detection event into ndvi_anomalies.
    persist: bool = True
    # Where the NDVI series comes from:
    #   'synthetic' (default) — deterministic per-tenant seasonal sinusoid.
    #   'live' — reads real Sentinel-2 NDVI rows from
    #     tenant_<id>.satellite_observations (populated by the ingestion
    #     service's Statistical API ingest task).
    data_source: NdviDataSource = "synthetic"


class NdviScanData(BaseModel):
    """Body of the SuccessResponse[T] returned by POST /ndvi/scan."""

    anomaly_id: UUID | None
    tenant_id: str
    detector_name: str
    detector_version: str

    # Window
    window_start: datetime
    window_end: datetime
    days_early_warning: int

    # Metrics
    ndvi_recent_mean: float
    ndvi_baseline_mean: float
    ndvi_baseline_std: float
    z_score: float
    disease_probability: float
    anomaly: bool
    confidence_band: ConfidenceBand

    # 90-day series for the chart
    series: list[NdviSamplePoint] = Field(default_factory=list)

    crop: str | None
    persisted: bool


class NdviAnomalyRow(BaseModel):
    """One row from `tenant_<id>.ndvi_anomalies`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    detector_name: str
    detector_version: str
    window_start: datetime
    window_end: datetime
    ndvi_recent_mean: float
    ndvi_baseline_mean: float
    ndvi_baseline_std: float
    z_score: float
    disease_probability: float
    anomaly: bool
    confidence_band: ConfidenceBand
    crop: str | None
    created_at: datetime


class NdviAnomalyListData(BaseModel):
    anomalies: list[NdviAnomalyRow] = Field(default_factory=list)


# ─── Bulk price CSV upload (Slice 04.b.live) ──────────────────────────────


class BulkPriceRowError(BaseModel):
    """One CSV row that couldn't be ingested. Returned alongside the
    inserted/skipped counts so the operator gets a clean diagnostic."""

    line_number: int                    # 1-based, includes header line
    raw_row: dict[str, str]             # echo of the offending cell values
    error: str


class BulkPriceUploadResult(BaseModel):
    """Summary returned from POST /cropguard/prices/bulk."""

    source: str                         # audit tag stamped on every row
    rows_received: int                  # total CSV data rows (excludes header)
    rows_inserted: int                  # upserts that landed (new or updated)
    rows_skipped: int                   # rows rejected — see errors[]
    crops_seen: list[str] = Field(default_factory=list)
    regions_seen: list[str] = Field(default_factory=list)
    errors: list[BulkPriceRowError] = Field(default_factory=list)
