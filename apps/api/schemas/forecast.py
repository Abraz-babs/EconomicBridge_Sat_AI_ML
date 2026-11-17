"""Response models for ShockGuard's forecast side (ECMWF open data).

Mirrors apps/frontend/src/hooks/useForecast.ts — keep the two in sync.
Every list is one value per day counted from `first_day` (the run date, a UTC
day). A product ECMWF did not publish for the run is None, never a stand-in.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from schemas.shockguard import LonLat

ECMWF_ATTRIBUTION = (
    "© 2026 European Centre for Medium-Range Weather Forecasts (ECMWF). Source: www.ecmwf.int. "
    "Licence: CC BY 4.0. Changed by EconomicBridge: 24-hour totals derived from accumulated "
    "fields, values averaged over each local area. ECMWF accepts no liability for errors or "
    "omissions in the data and does not endorse this product."
)


class ForecastArea(BaseModel):
    """What the newest run says for one LGA."""

    lga: str
    location: LonLat | None = None
    # 0.25 deg (~28 km) cells overlapping this LGA; its values are their area-weighted mean.
    cells: int
    rain_ifs_mm: list[float] = Field(description="Physics model (IFS), mm per day, 15 days")
    rain_ifs_max_mm: list[float] = Field(description="Wettest overlapping cell, mm per day")
    rain_aifs_mm: list[float] | None = Field(None, description="AI model (AIFS), mm per day")
    chance_1mm: list[int] | None = Field(None, description="% of the ensemble with 1 mm+, 10 days")
    chance_10mm: list[int] | None = None
    chance_25mm: list[int] | None = None
    chance_50mm: list[int] | None = None
    temp_dawn_c: list[float] | None = Field(None, description="2 m temperature at 06 UTC, 6 days")
    temp_afternoon_c: list[float] | None = Field(None, description="2 m temperature at 15 UTC, 6 days")


class ForecastFeed(BaseModel):
    """Health of the forecast feed for this tenant, from public.ingestion_runs."""

    last_success_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None


class ForecastData(BaseModel):
    """The newest stored run for the tenant; empty lists before the first run."""

    run_at: datetime | None = None
    first_day: date | None = None
    days: list[date] = Field(default_factory=list)
    areas: list[ForecastArea] = Field(default_factory=list)
    feed: ForecastFeed = Field(default_factory=ForecastFeed)
    source: str = "ecmwf_forecast_v1"
    attribution: str = ECMWF_ATTRIBUTION


class ForecastCellsData(BaseModel):
    """ECMWF's own 0.25 deg cells over the tenant, for the map's raw-grid layer.

    Lists are [day][row * n_cols + col]; rows run south from lat0, columns east
    from lon0, both cell centres.
    """

    run_at: datetime | None = None
    lat0: float | None = None
    lon0: float | None = None
    res: float = 0.25
    n_rows: int = 0
    n_cols: int = 0
    rain_ifs_mm: list[list[float]] = Field(default_factory=list)
    rain_aifs_mm: list[list[float]] | None = None
    chance_10mm: list[list[float]] | None = None
