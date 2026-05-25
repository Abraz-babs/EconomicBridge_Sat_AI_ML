"""Pydantic schemas for Module 07 — SkillsBridge."""
from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ConnectivityBand = Literal["no_signal", "limited", "basic", "broadband"]


class LonLat(BaseModel):
    lon: float
    lat: float


class SkillsIndicatorRow(BaseModel):
    """One LGA's education + connectivity profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    lga: str
    location: LonLat

    school_count: int
    school_density_per_10k: float
    internet_coverage_pct: float            # 0..100
    connectivity_band: ConnectivityBand     # derived
    mobile_coverage_pct: float              # 0..100
    electricity_reliability: float          # 0..1
    youth_population: int
    learning_gap_index: float               # 0..1 — higher = worse

    observed_at: DateType
    source: str
    created_at: datetime
    updated_at: datetime


class SkillsStatsData(BaseModel):
    """Aggregate body of GET /skills/indicators."""

    tenant_id: str
    total_lgas: int
    median_internet_coverage_pct: float
    median_school_density: float
    total_schools: int
    total_youth_population: int
    best_connectivity_lga: str | None
    worst_gap_lga: str | None
    most_underserved_lga: str | None        # lowest school_density_per_10k
    most_schools_lga: str | None
    indicators: list[SkillsIndicatorRow] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
