"""Pre-season risk profile — response models (GET /cropguard/risk-profile)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RiskOverlay(BaseModel):
    layer: str
    label: str
    bounds: list[float] = Field(description="west, south, east, north")
    image: str = Field(description="data:image/png;base64 greyscale mask (white = in the layer)")


class RiskLga(BaseModel):
    lga: str
    band_flood: str
    band_drought: str
    band_rains: str
    figures: dict


class MappedFloodSummary(BaseModel):
    key: str
    label: str
    cropland_ha: int
    lgas_with_water: int
    agreement: float | None = Field(
        default=None,
        description="Rank agreement (Spearman) between farmland in the 1-in-10-year zone and water seen, by LGA")


class RiskSummary(BaseModel):
    lgas: int
    cropland_ha: int
    rp10_cropland_ha: int
    rp100_cropland_ha: int
    mapped: list[MappedFloodSummary] = []
    bands: dict[str, dict[str, int]]
    seasons: int
    drought_seasons_min: int | None = None
    drought_seasons_max: int | None = None
    rains_seasons: int | None = None
    rains_failed_min: int | None = None
    rains_failed_max: int | None = None
    people: int | None = None


class RiskProfileData(BaseModel):
    available: bool
    through_season: int | None = None
    first_season: int | None = None
    rains_first_season: int | None = None
    method: str | None = None
    measured_at: datetime | None = None
    rule: dict[str, str] = {}
    summary: RiskSummary | None = None
    lgas: list[RiskLga] = []
    overlays: list[RiskOverlay] = []
    sources: str | None = None
