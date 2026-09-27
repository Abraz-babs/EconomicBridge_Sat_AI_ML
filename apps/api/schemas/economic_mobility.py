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
    # Dual currency: USD is the universal figure (every row); NGN is set for
    # Nigerian tenants only (ECOWAS pilots are USD-only). UI shows ₦X ($Y).
    avg_household_income_ngn: int | None = None
    avg_household_income_usd: int | None = None
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
    # Median income in both currencies. NGN is null for ECOWAS (USD-only)
    # tenants; USD is always present.
    median_household_income_ngn: int | None = None
    median_household_income_usd: int | None = None
    cheapest_lga: str | None
    most_expensive_lga: str | None
    best_opportunity_lga: str | None
    best_capacity_lga: str | None
    indicators: list[MobilityIndicatorRow] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ─── Night-light trend (GET /economic_mobility/light-trend) ──────────────

LightCategory = Literal["dimmer", "brighter", "new_light", "steady", "still_dark", "mixed"]


class LightTrendLga(BaseModel):
    """One LGA's light at night each year, on both of NASA's yearly composites."""

    lga: str
    location: LonLat | None = None
    years: list[int] = Field(default_factory=list)
    near_nadir: list[float | None] = Field(default_factory=list)   # summed radiance per year
    all_angle: list[float | None] = Field(default_factory=list)
    change_pct: float | None = None       # near-nadir: latest three years vs first three
    category: LightCategory
    lit_km2_start: float | None = None
    lit_km2_now: float | None = None
    people: int = 0
    villages: int = 0
    gone_dark: int = 0
    newly_lit: int = 0


class TrendVillage(BaseModel):
    """A village that went dark, or was newly lit, on both composites."""

    name: str
    ward: str | None = None
    lga: str | None = None
    location: LonLat
    people: int = 0
    since_year: int | None = None
    near_nadir: list[float | None] = Field(default_factory=list)


class StaplePrice(BaseModel):
    month: DateType
    price_ngn_per_kg: float


class StapleSeries(BaseModel):
    crop: str
    source: str
    points: list[StaplePrice] = Field(default_factory=list)


class LightTrendData(BaseModel):
    """Body of GET /economic_mobility/light-trend."""

    available: bool = False
    reason: str | None = None
    first_year: int | None = None
    last_year: int | None = None
    window: int = 3
    lgas: list[LightTrendLga] = Field(default_factory=list)
    dimmer: int = 0
    brighter: int = 0
    steady: int = 0
    still_dark: int = 0
    mixed: int = 0
    people_in_dimmer: int = 0
    gone_dark: int = 0
    gone_dark_people: int = 0
    newly_lit: int = 0
    newly_lit_people: int = 0
    villages_gone_dark: list[TrendVillage] = Field(default_factory=list)
    villages_newly_lit: list[TrendVillage] = Field(default_factory=list)
    prices: list[StapleSeries] = Field(default_factory=list)
