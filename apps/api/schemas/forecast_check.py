"""Response models for the forecast check: ECMWF's forecast against the rain
NASA's IMERG measured, LGA by LGA (ingestion: tasks/forecast_check.py).

Mirrors apps/frontend/src/hooks/useForecastCheck.ts — keep the two in sync.

Counts, not just ratios, travel to the page, so every percentage it shows can
carry its sample size. Count lists are positional to keep a season's record
small; their order is fixed here and in processors/rain_check.counts.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from schemas.forecast import ECMWF_ATTRIBUTION, ForecastFeed
from schemas.shockguard import LonLat

IMERG_CREDIT = (
    "Measured rain: NASA/JAXA GPM IMERG Late Run V07, daily, 0.1°, from the Goddard Earth "
    "Sciences Data and Information Services Center (GES DISC). A satellite estimate, not a "
    "rain gauge; averaged over each local area by EconomicBridge."
)

COUNTS_DOC = ("per lead 0..14 (days before the day the forecast was made): [hits, false alarms, "
              "misses, correct dry, forecast mm, measured mm, absolute error mm on pairs where "
              "either side was wet, those pairs, then hits, false alarms, misses, correct calls "
              "for soaking days of 10 mm+]")


class CheckDay(BaseModel):
    """One measured day in the ribbon."""

    day: date
    lgas: int = Field(description="LGAs measured that day")
    wet: int = Field(description="LGAs with 1 mm+ measured")
    max_mm: float
    max_lga: str
    ifs: list[list[int]] = Field(description="per shown lead: [hits, false alarms, misses, correct dry]")
    aifs: list[list[int]]


class CheckLga(BaseModel):
    """One LGA's own record over the window."""

    lga: str
    location: LonLat | None = None
    days: int
    wet: int
    ifs: list[list[float]] = Field(
        description="per shown lead: [hits, false alarms, misses, correct dry, forecast mm, measured mm]")
    aifs: list[list[float]]


class CheckChance(BaseModel):
    """The ensemble's chances of one threshold against the share of the LGA that got it."""

    brier: list[list[float | None]] = Field(description="per lead 0..9: [pairs, Brier score, base-rate score]")
    bins: dict[str, list[list[float]]] = Field(
        description="lead group -> per chance bin: [pairs, sum of chances %, sum of measured shares]")


class ForecastCheckData(BaseModel):
    """The newest scorecard for the tenant; empty before the first one."""

    computed_at: datetime | None = None
    first_day: date | None = None
    last_day: date | None = None
    days_checked: int = 0
    lga_days: int = 0
    pairs: int = 0
    wet_mm: float = 1.0
    heavy_mm: float = 10.0
    shown_leads: list[int] = Field(default_factory=list)
    chance_bins: list[int] = Field(default_factory=list)
    chance_groups: list[str] = Field(default_factory=list)
    recent_days: int = 30
    recent_from: date | None = None
    scorecard: dict[str, dict[str, list[list[float]]]] = Field(
        default_factory=dict, description=f"'all' or 'recent' -> model -> {COUNTS_DOC}")
    chances: dict[str, CheckChance] = Field(default_factory=dict, description="threshold mm -> check")
    ribbon: list[CheckDay] = Field(default_factory=list)
    lgas: list[CheckLga] = Field(default_factory=list)
    feed: ForecastFeed = Field(default_factory=ForecastFeed)
    product: str = "GPM_3IMERGDL.07"
    attribution: str = ECMWF_ATTRIBUTION
    measured_credit: str = IMERG_CREDIT


class CheckDayArea(BaseModel):
    """One LGA on one day: what was measured, and every forecast made for that day."""

    lga: str
    location: LonLat | None = None
    measured_mm: float
    measured_max_mm: float
    wet_share_1mm: float
    wet_share_10mm: float
    ifs_mm: list[float | None] = Field(description="forecast made k days before, k = 0..14; null = no run")
    aifs_mm: list[float | None]
    chance_1mm: list[float | None] = Field(description="k = 0..9")
    chance_10mm: list[float | None]


class ForecastCheckDayData(BaseModel):
    """Every measured LGA of the tenant on one day."""

    day: date | None = None
    areas: list[CheckDayArea] = Field(default_factory=list)
    product: str = "GPM_3IMERGDL.07"
