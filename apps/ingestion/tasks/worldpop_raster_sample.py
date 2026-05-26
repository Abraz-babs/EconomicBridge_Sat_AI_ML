"""WorldPop population raster sweep — Phase B (Slice 09).

For each pilot tenant, take every `poverty_villages` row and sample the
WorldPop 2020 population GeoTIFF at that (lon, lat). Persist the result
to `raster_samples` tagged `source='worldpop_ppp_v1'`, band_name
`population_per_km2`. The dashboard's Economic Visibility panel joins
village rows to the latest sample so analysts can compare seed-time
estimates against the real WorldPop pixel.

URL discovery
-------------
WorldPop publishes per-country annual rasters at:
  https://data.worldpop.org/GIS/Population/Global_2000_2020/{YEAR}/{ISO3}/{iso3}_ppp_{YEAR}.tif

These are ~1km / pixel population counts. WorldPop's distribution server
exposes the files as plain GeoTIFFs; recent uploads include COG-internal
tiling so HTTP range reads work via `/vsicurl/`. Where tiling is
absent rasterio falls back to a single full GET which is slow but
correct — fine for an overnight scheduled sweep.

Per-tenant ISO3 mapping
-----------------------
All eight Nigerian state pilots share the NGA national GeoTIFF; Ghana
and Senegal map to GHA and SEN respectively. Adding a new pilot is one
dict entry.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from sources.cog_sampler import CogSample, CogSamplerError, sample_points

log = logging.getLogger(__name__)


SOURCE_NAME = "worldpop_ppp_v1"
BAND_NAME = "population_per_km2"
OBSERVED_YEAR = 2020


TENANT_TO_ISO3: dict[str, str] = {
    # All Nigerian states share NGA
    "kebbi": "NGA", "benue": "NGA", "plateau": "NGA",
    "kaduna": "NGA", "niger": "NGA", "zamfara": "NGA",
    "nasarawa": "NGA", "fct": "NGA",
    "ghana": "GHA",
    "senegal": "SEN",
}


def worldpop_url_for(iso3: str, year: int = OBSERVED_YEAR) -> str:
    """Build the WorldPop PPP GeoTIFF URL for a given country."""
    iso3 = iso3.upper()
    return (
        f"https://data.worldpop.org/GIS/Population/Global_2000_2020/"
        f"{year}/{iso3}/{iso3.lower()}_ppp_{year}.tif"
    )


@dataclass(frozen=True, slots=True)
class _Village:
    """Minimal projection of a poverty_villages row for sampling."""
    settlement_name: str
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Summary of one tenant sweep, returned to the CLI / scheduler."""
    tenant_id: str
    requested: int       # villages we tried to sample
    valid: int           # samples with valid (non-nodata) value
    nodata: int          # samples that hit nodata or off-raster
    failed: bool         # True when the COG could not be opened
    error: str | None    # short error message when failed=True


async def _load_villages(
    session: AsyncSession, tenant_id: str,
) -> list[_Village]:
    await set_tenant_schema(session, tenant_id)
    rows = (await session.execute(text(
        "SELECT settlement_name, ST_X(location) AS lon, ST_Y(location) AS lat "
        "FROM poverty_villages WHERE source = 'seed_v1'"
    ))).mappings().all()
    return [_Village(
        settlement_name=r["settlement_name"],
        lon=float(r["lon"]), lat=float(r["lat"]),
    ) for r in rows]


async def _upsert_samples(
    session: AsyncSession,
    tenant_id: str,
    samples: list[tuple[_Village, CogSample]],
    granule_id: str,
) -> None:
    await set_tenant_schema(session, tenant_id)
    observed = date(OBSERVED_YEAR, 1, 1)
    captured = datetime.now(timezone.utc)
    # Upsert by the functional UNIQUE INDEX defined in migration 0024
    # (tenant_id, source, band_name, observed_at,
    #  ST_AsBinary(ST_SnapToGrid(location, 0.0001))).
    for village, sample in samples:
        await session.execute(text(
            """
            INSERT INTO raster_samples (
                tenant_id, location, source, band_name,
                value, valid, observed_at, captured_at,
                granule_id, linked_settlement_name
            ) VALUES (
                :tenant_id,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :source, :band, :value, :valid, :observed_at, :captured,
                :granule, :linked
            )
            ON CONFLICT (
                tenant_id, source, band_name, observed_at,
                (ST_AsBinary(ST_SnapToGrid(location, 0.0001)))
            ) DO UPDATE SET
                value         = EXCLUDED.value,
                valid         = EXCLUDED.valid,
                captured_at   = EXCLUDED.captured_at,
                granule_id    = EXCLUDED.granule_id,
                updated_at    = NOW()
            """
        ), {
            "tenant_id": tenant_id,
            "lon": village.lon, "lat": village.lat,
            "source": SOURCE_NAME, "band": BAND_NAME,
            "value": sample.value, "valid": sample.valid,
            "observed_at": observed, "captured": captured,
            "granule": granule_id,
            "linked": village.settlement_name,
        })


async def sweep_tenant(
    session: AsyncSession,
    tenant_id: str,
    *,
    url_override: str | None = None,
) -> SweepResult:
    """Sample the WorldPop COG at every poverty_villages row for one tenant
    and upsert the results into raster_samples. Returns a SweepResult so
    the caller can log / surface progress."""
    iso3 = TENANT_TO_ISO3.get(tenant_id)
    if iso3 is None and url_override is None:
        return SweepResult(
            tenant_id=tenant_id, requested=0, valid=0, nodata=0,
            failed=True,
            error=f"no WorldPop ISO3 mapping for tenant {tenant_id}",
        )

    url = url_override or worldpop_url_for(iso3 or "")
    villages = await _load_villages(session, tenant_id)
    if not villages:
        return SweepResult(
            tenant_id=tenant_id, requested=0, valid=0, nodata=0,
            failed=False, error=None,
        )

    points = [(v.lon, v.lat) for v in villages]
    try:
        # rasterio is sync C bindings — keep the event loop responsive.
        samples = await asyncio.to_thread(sample_points, url, points)
    except CogSamplerError as e:
        log.warning("worldpop sweep failed for %s: %s", tenant_id, e)
        return SweepResult(
            tenant_id=tenant_id, requested=len(villages),
            valid=0, nodata=0, failed=True, error=str(e),
        )

    pairs = list(zip(villages, samples))
    await _upsert_samples(session, tenant_id, pairs, granule_id=url)
    await session.commit()

    valid_n = sum(1 for s in samples if s.valid)
    nodata_n = len(samples) - valid_n
    log.info(
        "worldpop %s: %d sampled (%d valid, %d nodata) from %s",
        tenant_id, len(samples), valid_n, nodata_n, url,
    )
    return SweepResult(
        tenant_id=tenant_id, requested=len(villages),
        valid=valid_n, nodata=nodata_n, failed=False, error=None,
    )


async def sweep_all(
    session: AsyncSession, tenant_ids: list[str],
) -> list[SweepResult]:
    """Run sweep_tenant sequentially across `tenant_ids`. Sequential
    rather than concurrent so we never hammer WorldPop's CDN."""
    out: list[SweepResult] = []
    for tid in tenant_ids:
        out.append(await sweep_tenant(session, tid))
    return out
