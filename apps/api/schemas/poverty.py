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

    # Phase B raster samples (Slice 09): the latest per-pixel read of
    # the WorldPop population GeoTIFF at this village's coords. Null
    # when no sweep has covered this row yet.
    latest_worldpop_sample: float | None = None
    worldpop_sampled_at: datetime | None = None

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
    # Phase B (Slice 09): how many villages have been enriched with a
    # real WorldPop raster sample. Lets the dashboard show "12 of 92
    # villages have real WorldPop pixel data".
    raster_sampled_villages: int = 0
    villages: list[PovertyVillage] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ─── Village light (migration 0054) — measured, at real villages ─────────────
# Replaces the generated "settlement N" points above for the panel. Every
# figure is a measurement: VIIRS night light, HRSL people, GRID3 names.


class VillageLightStats(BaseModel):
    villages: int
    unlit: int
    dim: int
    lit: int
    unknown: int
    # Unlit on the dry-season read AND the wet-season check.
    unlit_both_seasons: int
    people: int
    people_unlit: int
    under5_unlit: int


class LgaLightRow(BaseModel):
    lga: str
    villages: int
    unlit: int
    people_unlit: int
    under5_unlit: int


class UnlitVillage(BaseModel):
    name: str
    ward: str | None = None
    lga: str | None = None
    location: LonLat
    people: int
    under5: int
    radiance_dry: float | None = None
    radiance_wet: float | None = None
    light_class_wet: str | None = None


class VillageLightData(BaseModel):
    """Payload of GET /economic_visibility/village-light."""

    period: str | None
    periods: list[str]
    dry_window: str | None = None
    wet_window: str | None = None
    sources: str | None = None
    stats: VillageLightStats | None = None
    lgas: list[LgaLightRow] = Field(default_factory=list)
    top_unlit: list[UnlitVillage] = Field(default_factory=list)
    # Every village for the map, compact: [lon, lat, class, wet class, people];
    # class codes 0 unlit · 1 dim · 2 lit · 3 unknown.
    points: list[list[float]] = Field(default_factory=list)
