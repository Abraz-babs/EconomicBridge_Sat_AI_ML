"""Pydantic schemas for Module 01 — Poverty Mapping (Economic Visibility)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LonLat(BaseModel):
    lon: float
    lat: float


class PovertyVillage(BaseModel):
    """One row from `tenant_<id>.poverty_villages`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    settlement_name: str
    lga: str
    location: LonLat
    poverty_score: float
    population: int
    households_unreached: int
    nightlight_dimness: float
    has_dhs_data: bool

    # Real-source provenance (null when source='seed_v1')
    viirs_pixel_radiance: float | None = None
    worldpop_estimate: float | None = None

    source: str
    created_at: datetime
    updated_at: datetime


class PovertyStatsData(BaseModel):
    """Aggregate stats + village list for the dashboard."""

    tenant_id: str
    villages_identified: int
    population_estimated: int
    households_unreached: int
    coverage_pct: float
    verification_pct: float
    villages: list[PovertyVillage] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
