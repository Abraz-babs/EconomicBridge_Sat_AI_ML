"""Bridge between tenant_<id>.satellite_observations and the pure-Python
detectors in services/shock_detector.py + services/ndvi_anomaly.py.

The detectors take simple typed tuples (FloodSeriesPoint, NdviSample).
The satellite_observations table is populated by the ingestion service
via the Sentinel Hub Statistical API (apps/ingestion/tasks/
satellite_observations_ingest.py). This module is the glue layer:
read rows for one tenant, reshape into the detector's input type, hand
back. The detectors stay DB-ignorant so they remain unit-testable
without spinning up Postgres.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ndvi_anomaly import NdviSample, SERIES_LENGTH_DAYS
from services.shock_detector import FloodSeriesPoint


LIVE_SOURCE: str = "sentinel_stat_v1"

# Live SAR query window. Decoupled from the synthetic FLOOD_SERIES_DAYS (60d):
# single-orbit ROIs only yield ~10 Sentinel-1 passes in 60d, below the ≥12
# detector floor. The ingest now pulls a 120d S1 window, so we read 130d here
# (one repeat-cycle of margin) to pick up every real pass that was stored.
LIVE_SAR_WINDOW_DAYS: int = 130


class LiveDataMissingError(RuntimeError):
    """Raised when the caller asked for live data but the ingest task
    hasn't populated enough rows for this tenant yet."""


async def load_flood_series(
    session: AsyncSession,
    *,
    end: datetime | None = None,
    min_points: int | None = None,
) -> tuple[FloodSeriesPoint, ...]:
    """Pull SAR rows from tenant_<id>.satellite_observations.

    Caller must have already set search_path via tenant middleware.
    Returns oldest-first so the detector's windowing math (which assumes
    chronological order) works without resorting.
    """
    if end is None:
        end = datetime.now(timezone.utc)
    cutoff = (end - timedelta(days=LIVE_SAR_WINDOW_DAYS)).date()

    result = await session.execute(
        text(
            """
            SELECT observed_at, sar_backscatter_db
              FROM satellite_observations
             WHERE dataset = 'sentinel-1-grd'
               AND source  = :source
               AND sar_backscatter_db IS NOT NULL
               AND observed_at >= :cutoff
             ORDER BY observed_at ASC
            """
        ),
        {"source": LIVE_SOURCE, "cutoff": cutoff},
    )
    rows = result.mappings().all()
    series = tuple(
        FloodSeriesPoint(
            observed_at=r["observed_at"],
            backscatter_db=float(r["sar_backscatter_db"]),
        )
        for r in rows
    )

    # Floor matches the live-mode windows in routers/shockguard.py:
    # recent_n=3 + baseline_n=8 = 11 points minimum. 12 leaves one row
    # of slack so an off-by-one acquisition gap doesn't error.
    floor = min_points if min_points is not None else 12
    if len(series) < floor:
        raise LiveDataMissingError(
            f"Live flood detection needs at least {floor} recent Sentinel-1 SAR "
            f"passes for this area; only {len(series)} are available so far. "
            "Showing the modelled estimate instead — live coverage builds up as "
            "more satellite passes are collected."
        )
    return series


async def load_ndvi_series(
    session: AsyncSession,
    *,
    end: datetime | None = None,
    min_points: int | None = None,
) -> tuple[NdviSample, ...]:
    """Pull NDVI rows from tenant_<id>.satellite_observations.

    Same shape as load_flood_series: caller has search_path set, we
    return oldest-first, raise LiveDataMissingError when sparse.
    """
    if end is None:
        end = datetime.now(timezone.utc)
    cutoff = (end - timedelta(days=SERIES_LENGTH_DAYS)).date()

    result = await session.execute(
        text(
            """
            SELECT observed_at, ndvi_mean
              FROM satellite_observations
             WHERE dataset = 'sentinel-2-l2a'
               AND source  = :source
               AND ndvi_mean IS NOT NULL
               AND observed_at >= :cutoff
             ORDER BY observed_at ASC
            """
        ),
        {"source": LIVE_SOURCE, "cutoff": cutoff},
    )
    rows = result.mappings().all()
    series = tuple(
        NdviSample(
            observed_at=r["observed_at"],
            ndvi=float(r["ndvi_mean"]),
        )
        for r in rows
    )

    # Floor matches the live-mode windows in routers/cropguard_ndvi.py:
    # recent_n=3 + baseline_n=12 = 15 points minimum. 16 leaves one row
    # of slack for a missed acquisition.
    floor = min_points if min_points is not None else 16
    if len(series) < floor:
        raise LiveDataMissingError(
            f"Live vegetation analysis needs at least {floor} recent Sentinel-2 "
            f"NDVI passes for this area; only {len(series)} are available so far. "
            "Showing the modelled estimate instead — live coverage builds up as "
            "more satellite passes are collected."
        )
    return series
