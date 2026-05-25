"""Pydantic schemas for Module 06 — Economic Mobility Compass."""
from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


CompareBand = Literal["below_avg", "near_avg", "above_avg", "premium"]


class LonLat(BaseModel):
    lon: float
    lat: float


class MobilityIndicatorRow(BaseModel):
    """One LGA's mobility profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    lga: str
    location: LonLat

    cost_of_living_index: float        # 100 = national average
    cost_of_living_band: CompareBand   # derived
    avg_household_income_ngn: int
    income_opportunity_score: float    # 0..1
    displacement_capacity_index: float # 0..1
    population: int

    observed_at: DateType
    source: str
    created_at: datetime
    updated_at: datetime


class MobilityStatsData(BaseModel):
    """Aggregate body of GET /economic_mobility/indicators."""

    tenant_id: str
    total_lgas: int
    median_cost_of_living: float
    median_household_income_ngn: int
    cheapest_lga: str | None
    most_expensive_lga: str | None
    best_opportunity_lga: str | None
    best_capacity_lga: str | None
    indicators: list[MobilityIndicatorRow] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
