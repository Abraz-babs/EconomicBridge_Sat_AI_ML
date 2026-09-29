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
    """One LGA's school count from the GRID3 school register.

    Rebuilt 2026-09-29: only the count is measured. The connectivity, power,
    youth-population and learning-gap figures this row used to carry were
    modelled around per-LGA hashes (skills_indicators, GIGA/ITU path) and are
    withdrawn — the fields stay in the contract and are always null.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    tenant_id: str
    lga: str
    location: LonLat | None = None

    school_count: int
    school_density_per_10k: float | None = None
    internet_coverage_pct: float | None = None
    connectivity_band: ConnectivityBand | None = None
    mobile_coverage_pct: float | None = None
    electricity_reliability: float | None = None
    youth_population: int | None = None
    learning_gap_index: float | None = None

    observed_at: DateType | None = None
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillsStatsData(BaseModel):
    """Aggregate body of GET /skills/indicators."""

    tenant_id: str
    total_lgas: int
    median_internet_coverage_pct: float | None = None
    median_school_density: float | None = None
    total_schools: int
    total_youth_population: int | None = None
    best_connectivity_lga: str | None
    worst_gap_lga: str | None
    most_underserved_lga: str | None        # lowest school_density_per_10k
    most_schools_lga: str | None
    indicators: list[SkillsIndicatorRow] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ─── School reach list (GET /skills/reach) ────────────────────────────────

SchoolLight = Literal["dark", "lit", "unknown"]


class ReachSchool(BaseModel):
    """One GRID3 school and the villages around it.

    `light` is "dark" when no village within 2 km shows light at night (lit
    or dim), "lit" when at least one does, "unknown" when no named village
    lies within 2 km. `rank` places a dark school on the reach list — one
    school per village, most people first; None for every other school.
    """

    name: str
    category: str | None = None
    management: str | None = None
    lga: str | None = None
    location: LonLat
    light: SchoolLight
    rank: int | None = None
    village: str | None = None
    ward: str | None = None
    village_km: float | None = None
    village_light: str | None = None
    people: int | None = None                # living nearest the school's village
    under5: int | None = None
    villages_2km: int = 0
    lit_villages_2km: int = 0
    people_2km: int = 0                      # every village within 2 km
    under5_2km: int = 0


class ReachLga(BaseModel):
    lga: str
    schools: int
    assessed: int                            # with a named village within 2 km
    dark: int
    dark_pct: float | None = None            # of assessed


class SchoolReachData(BaseModel):
    """Body of GET /skills/reach."""

    available: bool = False
    reason: str | None = None                # why not, when unavailable
    state: str | None = None
    light_round: str | None = None           # village-light period, e.g. "2026"
    light_window: str | None = None          # the dry-season nights measured
    schools: int = 0
    assessed: int = 0
    dark: int = 0
    dark_pct: float | None = None
    primary: int = 0
    secondary: int = 0
    dark_villages: int = 0                   # distinct villages on the reach list
    people: int = 0                          # living in those villages
    under5: int = 0
    lgas: list[ReachLga] = Field(default_factory=list)
    rows: list[ReachSchool] = Field(default_factory=list)
