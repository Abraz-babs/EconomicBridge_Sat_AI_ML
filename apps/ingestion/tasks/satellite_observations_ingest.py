"""Pull Sentinel-1 SAR + Sentinel-2 NDVI time series → satellite_observations.

Per-tenant, per-dataset ingest task that hits the CDSE Statistical API,
parses StatPoints, and upserts rows into tenant_<id>.satellite_observations.
Module 05 ShockGuard (flood + drought detectors) and Module 04 NDVI
anomaly detection both read from that table when data_source='live'.

Window defaults:
  Sentinel-1 GRD  — 60-day window, daily aggregation
                    (matches FLOOD_SERIES_DAYS in services/shock_detector.py)
  Sentinel-2 L2A  — 90-day window, daily aggregation
                    (matches NDVI_BASELINE_DAYS + RECENT_WINDOW_DAYS in
                    services/ndvi_anomaly.py; spans the dry→wet transition
                    where anomalies actually matter)

Idempotent by design: the upsert key is
(tenant_id, observed_at, dataset, source) so re-running the same window
over the same pilot replaces rows cleanly. Different sources for the
same key coexist ('sentinel_stat_v1' from live ingest vs 'detector_v1'
from the synthetic fallback path) so the dashboard can show divergence
as a data-quality cross-check.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, set_tenant_schema
from sources.copernicus import CopernicusClient
from sources.nasa_firms import PILOT_BBOX
from sources.sentinel_statistical import (
    EVALSCRIPT_S1_VV_DB,
    EVALSCRIPT_S2_NDVI,
    SentinelStatisticalClient,
    StatPoint,
)

log = logging.getLogger(__name__)


# Window sizes match the detector defaults so an ingest fills exactly what
# the detector reads. Tighter would force the detector to short-window;
# wider would burn PU on data the detector throws away.
S1_WINDOW_DAYS: int = 60
S2_WINDOW_DAYS: int = 90
LIVE_SOURCE: str = "sentinel_stat_v1"
S2_MAX_CLOUD_COVER_PCT: float = 40.0   # CDSE recommends 30-50 for vegetation indices


@dataclass(frozen=True, slots=True)
class ObservationIngestResult:
    """Per-tenant summary returned to the caller / scheduler."""

    tenant_id: str
    s1_points: int           # SAR rows upserted
    s2_points: int           # NDVI rows upserted
    s1_window_days: int
    s2_window_days: int


async def ingest_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    statistical_client: SentinelStatisticalClient,
    end: datetime | None = None,
    include_sar: bool = True,
    include_ndvi: bool = True,
) -> ObservationIngestResult:
    """End-to-end ingest for one tenant. Caller manages session/commit."""
    if tenant_id not in PILOT_TENANT_IDS:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")
    bbox = PILOT_BBOX.get(tenant_id)
    if bbox is None:
        raise ValueError(f"No bbox for tenant {tenant_id}")

    end_dt = (end or datetime.now(timezone.utc)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    await set_tenant_schema(session, tenant_id)

    s1_count = 0
    if include_sar:
        s1_start = end_dt - timedelta(days=S1_WINDOW_DAYS)
        s1_points = await statistical_client.compute_time_series(
            bbox=bbox, start=s1_start, end=end_dt,
            dataset="sentinel-1-grd", evalscript=EVALSCRIPT_S1_VV_DB,
        )
        for point in s1_points:
            if await _upsert_s1(session, tenant_id=tenant_id, point=point):
                s1_count += 1

    s2_count = 0
    if include_ndvi:
        s2_start = end_dt - timedelta(days=S2_WINDOW_DAYS)
        s2_points = await statistical_client.compute_time_series(
            bbox=bbox, start=s2_start, end=end_dt,
            dataset="sentinel-2-l2a", evalscript=EVALSCRIPT_S2_NDVI,
            max_cloud_cover_pct=S2_MAX_CLOUD_COVER_PCT,
        )
        for point in s2_points:
            if await _upsert_s2(session, tenant_id=tenant_id, point=point):
                s2_count += 1

    log.info(
        "satellite.ingest tenant=%s s1=%d s2=%d (window s1=%dd s2=%dd)",
        tenant_id, s1_count, s2_count, S1_WINDOW_DAYS, S2_WINDOW_DAYS,
    )

    return ObservationIngestResult(
        tenant_id=tenant_id,
        s1_points=s1_count,
        s2_points=s2_count,
        s1_window_days=S1_WINDOW_DAYS,
        s2_window_days=S2_WINDOW_DAYS,
    )


async def _upsert_s1(
    session: AsyncSession, *, tenant_id: str, point: StatPoint,
) -> bool:
    """Upsert one SAR row. Returns False when mean is None (no data this day)."""
    if point.mean is None:
        return False
    observed = _interval_to_date(point.interval_from)
    await _upsert(
        session,
        tenant_id=tenant_id,
        observed_at=observed,
        dataset="sentinel-1-grd",
        sar_backscatter_db=point.mean,
        ndvi_mean=None,
        lst_anomaly_c=None,
        point=point,
    )
    return True


async def _upsert_s2(
    session: AsyncSession, *, tenant_id: str, point: StatPoint,
) -> bool:
    if point.mean is None:
        return False
    observed = _interval_to_date(point.interval_from)
    await _upsert(
        session,
        tenant_id=tenant_id,
        observed_at=observed,
        dataset="sentinel-2-l2a",
        sar_backscatter_db=None,
        ndvi_mean=point.mean,
        lst_anomaly_c=None,
        point=point,
    )
    return True


async def _upsert(
    session: AsyncSession,
    *,
    tenant_id: str,
    observed_at: date,
    dataset: str,
    sar_backscatter_db: float | None,
    ndvi_mean: float | None,
    lst_anomaly_c: float | None,
    point: StatPoint,
) -> None:
    """ON CONFLICT (tenant_id, observed_at, dataset, source) → update values."""
    await session.execute(
        text(
            """
            INSERT INTO satellite_observations (
                tenant_id, observed_at, dataset,
                sar_backscatter_db, ndvi_mean, lst_anomaly_c,
                sample_count, stat_min, stat_max, stat_std, source
            ) VALUES (
                :tenant_id, :observed_at, :dataset,
                :sar, :ndvi, :lst,
                :sample_count, :stat_min, :stat_max, :stat_std, :source
            )
            ON CONFLICT (tenant_id, observed_at, dataset, source) DO UPDATE
              SET sar_backscatter_db = EXCLUDED.sar_backscatter_db,
                  ndvi_mean          = EXCLUDED.ndvi_mean,
                  lst_anomaly_c      = EXCLUDED.lst_anomaly_c,
                  sample_count       = EXCLUDED.sample_count,
                  stat_min           = EXCLUDED.stat_min,
                  stat_max           = EXCLUDED.stat_max,
                  stat_std           = EXCLUDED.stat_std
            """
        ),
        {
            "tenant_id": tenant_id,
            "observed_at": observed_at,
            "dataset": dataset,
            "sar": sar_backscatter_db,
            "ndvi": ndvi_mean,
            "lst": lst_anomaly_c,
            "sample_count": point.sample_count,
            "stat_min": point.min_value,
            "stat_max": point.max_value,
            "stat_std": point.std_dev,
            "source": LIVE_SOURCE,
        },
    )


def _interval_to_date(dt: datetime) -> date:
    """Statistical API returns interval bounds at UTC midnight. The date
    that contains the interval IS its `from` date."""
    return dt.date()


async def ingest_all(
    session_factory,
    *,
    statistical_http: httpx.AsyncClient | None = None,
    end: datetime | None = None,
    tenants: list[str] | None = None,
) -> list[ObservationIngestResult]:
    """Run ingest_tenant() for every pilot tenant. Returns per-tenant summaries."""
    copernicus = CopernicusClient(http=statistical_http)
    statistical = SentinelStatisticalClient(copernicus)
    selected = tenants or sorted(PILOT_TENANT_IDS)
    results: list[ObservationIngestResult] = []
    async with session_factory() as session:
        for tenant_id in selected:
            result = await ingest_tenant(
                session, tenant_id=tenant_id,
                statistical_client=statistical, end=end,
            )
            results.append(result)
        await session.commit()
    return results
