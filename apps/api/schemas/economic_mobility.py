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

    # None since 2026-09-29: never measured per LGA (was a profile + noise).
    cost_of_living_index: float | None = None
    cost_of_living_band: CompareBand | None = None
    # Dual currency: USD is the universal figure (every row); NGN is set for
    # Nigerian tenants only (ECOWAS pilots are USD-only). UI shows ₦X ($Y).
    avg_household_income_ngn: int | None = None
    avg_household_income_usd: int | None = None
    # The World Bank's national employment-to-population ratio, as published.
    income_opportunity_score: float | None = None
    # Withdrawn 2026-09-29 (a formula over noise; a hashed population): null.
    displacement_capacity_index: float | None = None
    population: int | None = None

    observed_at: DateType
    source: str
    created_at: datetime
    updated_at: datetime


class MobilityStatsData(BaseModel):
    """Aggregate body of GET /economic_mobility/indicators."""

    tenant_id: str
    total_lgas: int
    median_cost_of_living: float | None = None
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


# ─── The compass: five measured factors per LGA (2026-09-28) ─────────────


class CompassPricePoint(BaseModel):
    month: DateType
    price_ngn: float


class CompassPrice(BaseModel):
    """One price tile: an item, where it was priced, and how."""

    item: str                      # petrol | maize | sorghum | rice | gari | millet | cowpea
    unit: str                      # litre | kg
    publisher: str                 # World Bank | FEWS NET | NBS
    place: str                     # "Kaura Namoda market", "North West average", …
    modelled: bool = False         # World Bank model estimates (every month) vs published prices
    last_surveyed: DateType | None = None   # World Bank: the last month a price was surveyed there
    stale: bool = False            # nothing published in the last six months
    points: list[CompassPricePoint] = Field(default_factory=list)


class CompassLga(BaseModel):
    lga: str
    location: LonLat | None = None
    people: int = 0                        # at the LGA's GRID3 villages (Meta & CIESIN)
    light_category: str | None = None      # as /light-trend
    light_change_pct: float | None = None
    season_pct: float | None = None        # farmland greenness vs last season, same ground
    walk_median_min: float | None = None   # people-weighted
    drive_median_min: float | None = None
    over_hour_walk_people: int = 0
    over_hour_walk_share: float | None = None   # 0..1 of people with a travel time
    facilities: int | None = None          # located GRID3 health facilities
    facilities_per_10k: float | None = None
    storms: int = 0                        # half-hourly storm events this rainy season
    advisories: int = 0                    # extreme-rain advisory days this rainy season
    signals: list[str] = Field(default_factory=list)


class FarVillage(BaseModel):
    name: str
    ward: str | None = None
    lga: str | None = None
    location: LonLat
    people: int = 0
    walk_min: float
    drive_min: float | None = None


class CompassData(BaseModel):
    """Mobility Compass — activity, farming, the walk to care, facilities and
    prices for every LGA, side by side. Signals are a count, never a score."""

    available: bool = False
    reason: str | None = None
    season_year: int | None = None
    previous_year: int | None = None
    season_state_pct: float | None = None
    season_since: DateType | None = None       # storms and advisories counted from here
    people: int = 0
    over_hour_walk_people: int = 0
    walk_median_min: float | None = None
    access_measured: bool = False
    facilities_release: str | None = None      # "v3.0" | "v2.0"
    facilities_total: int | None = None
    facilities_unlocated: int | None = None
    lgas: list[CompassLga] = Field(default_factory=list)
    far_from_care: list[FarVillage] = Field(default_factory=list)
    prices: list[CompassPrice] = Field(default_factory=list)
    income_usd_month: int | None = None        # state-level estimate, rounded
    income_ngn_month: int | None = None
