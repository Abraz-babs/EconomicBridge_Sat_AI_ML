"""Pydantic schemas for CropGuard Farm Check records.

A saved Farm Check is one field observation: the coordinate + crop an operator
checked, plus the satellite reading returned by the ingestion service
(apps/ingestion/sources/farm_check.py). The API service owns the persisted
table `tenant_<id>.farm_checks` (migration 0030) — read + write — so the
satellite tier keeps a recallable history alongside the leaf-photo tier
(crop_predictions).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


FarmHealth = Literal["healthy", "moderate", "stressed", "poor", "bare", "unknown"]
StressLevel = Literal["none", "moderate", "high", "unknown"]


class FarmTrendPoint(BaseModel):
    date: str
    ndvi: float


class FarmPassPoint(BaseModel):
    date: str
    ndvi: float
    health: str
    verdict: str
    sample_count: int
    cloud_affected: bool


class FarmStress(BaseModel):
    level: StressLevel
    z: float | None = None
    message: str = ""


class FarmCheckSaveRequest(BaseModel):
    """Body of POST /cropguard/farm-checks — the Farm Check result to record.

    Mirrors the ingestion FarmCheckResponse plus the `lga` record tag. The
    state is the X-Tenant-Id header (never the body), and `detail` is built
    server-side from trend/passes/stress so a recalled record is faithful.
    """

    model_config = ConfigDict(extra="ignore")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    crop: str = Field(default="general", max_length=60)
    lga: str | None = Field(default=None, max_length=120)
    owner_name: str | None = Field(default=None, max_length=160,
                                   description="Farm owner / farmer full name (optional record tag).")

    ndvi: float | None = None
    ndvi_date: str | None = None
    health: FarmHealth = "unknown"
    verdict: str = ""

    sar_db: float | None = None
    sar_date: str | None = None

    stress: FarmStress | None = None
    trend: list[FarmTrendPoint] = Field(default_factory=list)
    passes: list[FarmPassPoint] = Field(default_factory=list)

    sample_count: int = 0
    area_ha: float = 0.0
    resolution_m: int = 11
    source: str = "copernicus_sentinel_v1"
    note: str = ""


class FarmCheckSaveData(BaseModel):
    record_id: UUID
    saved: bool


class FarmCheckRecordRow(BaseModel):
    """One saved row from `tenant_<id>.farm_checks`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str

    lat: float
    lon: float
    crop: str
    lga: str | None = None
    owner_name: str | None = None

    ndvi: float | None = None
    ndvi_date: str | None = None
    health: str
    verdict: str

    sar_db: float | None = None
    sar_date: str | None = None

    stress: FarmStress | None = None
    trend: list[FarmTrendPoint] = Field(default_factory=list)
    passes: list[FarmPassPoint] = Field(default_factory=list)

    sample_count: int
    area_ha: float
    resolution_m: int
    source: str
    note: str | None = None

    created_at: datetime


class FarmCheckRecordListData(BaseModel):
    records: list[FarmCheckRecordRow] = Field(default_factory=list)
