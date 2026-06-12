"""Poverty-signal ingest task: VIIRS + WorldPop catalogs → poverty_villages.

Walks the pilot tenants and, for each:
  1. Resolves the tenant ROI bbox.
  2. Asks LAADS DAAC for the latest VIIRS Black Marble granule (or None
     when no Earthdata token is configured / no granule yet for the day).
  3. Asks WorldPop for the latest population layer for the country.
  4. Loads the seed-village coordinate list from apps/api scripts as the
     point grid to attach signals to (real settlement geometry lands when
     the operator imports OpenStreetMap settlement polygons in Phase B).
  5. Composes one PovertySignal per settlement and upserts a row in
     `tenant_<id>.poverty_villages` tagged with the appropriate live
     source (viirs_v2 / worldpop_v1) — falls back to seed_v1 when both
     catalogs are unavailable.

Idempotent: the upsert deletes the previous row for that (tenant, lga,
settlement_name, source) tuple before re-inserting, so re-runs of the same
catalog day don't bloat the table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, set_tenant_schema
from processors.poverty_signals import (
    PovertySettlementInput,
    PovertySignal,
    compose_signals,
)
from sources.nasa_firms import PILOT_BBOX
from sources.viirs_black_marble import BlackMarbleClient, BlackMarbleGranule
from sources.worldpop import WorldPopClient, WorldPopLayer

log = logging.getLogger(__name__)

# VNP46A2 nightlight granules publish ~1 week behind real time, so searching
# "today" always returns nothing. Default the VIIRS search back by this many
# days to pick up the latest actually-published granule. WorldPop is annual,
# unaffected.
VIIRS_LATENCY_DAYS = 10

# NASA's publication lag VARIES — a fixed-lag day regularly 404s (observed:
# day now-10 missing while older days exist). Walk further back, two days at
# a time, until a published day is found. 10 + 16 = up to 26 days back.
VIIRS_PROBE_STEP_DAYS = 2
VIIRS_PROBE_MAX_EXTRA_DAYS = 16

# The archive day that worked is the same for every tenant — resolve it once
# per process run instead of re-probing 10×. Keyed by the probe start date.
_resolved_viirs_date: dict[str, datetime] = {}


async def _latest_published_viirs_date(
    viirs_client: BlackMarbleClient,
    bbox: tuple[float, float, float, float],
    start: datetime,
) -> tuple[datetime, list[BlackMarbleGranule]]:
    """Find the most recent VIIRS day that actually has published granules.

    Starts at `start` (now - VIIRS_LATENCY_DAYS) and steps further back until
    granules appear or the probe window is exhausted. Returns the resolved
    date plus its granules ([] when nothing in the window is published).
    """
    key = start.strftime("%Y-%m-%d")
    if key in _resolved_viirs_date:
        d = _resolved_viirs_date[key]
        return d, await viirs_client.search_granules(bbox=bbox, date=d, max_results=4)

    for extra in range(0, VIIRS_PROBE_MAX_EXTRA_DAYS + 1, VIIRS_PROBE_STEP_DAYS):
        candidate = start - timedelta(days=extra)
        granules = await viirs_client.search_granules(
            bbox=bbox, date=candidate, max_results=4,
        )
        if granules:
            _resolved_viirs_date[key] = candidate
            if extra:
                log.info(
                    "viirs: day %s unpublished — using %s (%dd further back)",
                    start.date(), candidate.date(), extra,
                )
            return candidate, granules
    return start, []


# Per-tenant centroid + LGA pool. Mirrors apps/api/scripts/seed_poverty_villages.py
# verbatim so the same settlement points get assigned a real source row
# during the seed→live swap. When the operator ingests OpenStreetMap
# settlement polygons in Phase B, this list is replaced by the spatial join.
TENANT_CENTROIDS: dict[str, tuple[float, float]] = {
    "kebbi":    (4.55, 12.00),
    "benue":    (8.85, 7.20),
    "plateau":  (9.25, 9.45),
    "kaduna":   (8.15, 10.40),
    "niger":    (5.50, 10.30),
    "zamfara":  (6.50, 12.30),
    "nasarawa": (8.40, 8.85),
    "fct":      (7.49, 9.06),
    "ghana":    (-1.10, 7.95),
    "senegal":  (-14.45, 14.50),
}

# Subset of the LGA pool kept here. Full canonical pool is in
# apps/api/scripts/seed_poverty_villages.py; we sample 4 LGAs × 2
# settlements per tenant in the live path so the catalog hit-rate stays
# audit-friendly (a 100-settlement ingest amplifies every catalog blip).
LGA_SAMPLE: dict[str, list[str]] = {
    "kebbi":   ["Argungu", "Birnin Kebbi", "Dandi", "Jega"],
    "benue":   ["Agatu", "Logo", "Tarka", "Guma"],
    "plateau": ["Bassa", "Riyom", "Bokkos", "Jos North"],
    "kaduna":  ["Birnin Gwari", "Zangon Kataf", "Chikun", "Igabi"],
    "niger":   ["Shiroro", "Kontagora", "Mariga", "Bida"],
    "zamfara": ["Maru", "Anka", "Gusau", "Tsafe"],
    "nasarawa":["Akwanga", "Wamba", "Lafia", "Karu"],
    "fct":     ["Abaji", "Bwari", "Gwagwalada", "Kuje"],
    "ghana":   ["Pusiga", "Tamale", "Bolgatanga", "Wa"],
    "senegal": ["Kolda", "Kédougou", "Saint-Louis", "Matam"],
}


@dataclass(frozen=True, slots=True)
class PovertyIngestResult:
    """Summary returned to the caller / scheduler."""

    tenant_id: str
    viirs_granule_id: str | None
    worldpop_dataset_id: int | None
    settlements_total: int
    rows_written: int
    sources_observed: tuple[str, ...]


async def _seed_settlements(
    session: AsyncSession, tenant_id: str,
) -> list[PovertySettlementInput]:
    """Settlement points (+ coords) from the tenant's seed_v1 rows.

    Reusing the seed geometry keeps live rows at the same hand-curated LGA
    centroids as the seed (apps/api services/lga_geo.py) — no coordinate
    drift between the seed and live sources, mirroring the mobility/skills
    ingests. Returns [] when the tenant hasn't been seeded yet, in which
    case the caller falls back to `settlements_for()`.
    """
    await set_tenant_schema(session, tenant_id)
    rows = (await session.execute(text(
        "SELECT settlement_name, lga, ST_X(location) AS lon, ST_Y(location) AS lat "
        "FROM poverty_villages WHERE source = 'seed_v1'"
    ))).mappings().all()
    return [
        PovertySettlementInput(
            settlement_name=r["settlement_name"], lga=r["lga"],
            lon=float(r["lon"]), lat=float(r["lat"]),
        )
        for r in rows
    ]


def settlements_for(tenant_id: str) -> list[PovertySettlementInput]:
    """Fallback synthetic settlements when a tenant has no seed_v1 rows.

    Two points per LGA on a deterministic ring around the tenant centroid.
    Only used pre-seed; the live path normally reuses the seed geometry via
    `_seed_settlements()` so coordinates match the dashboard exactly.
    """
    centroid_lon, centroid_lat = TENANT_CENTROIDS.get(tenant_id, (0.0, 0.0))
    lgas = LGA_SAMPLE.get(tenant_id, [f"{tenant_id} Region 1"])
    out: list[PovertySettlementInput] = []
    for i, lga in enumerate(lgas):
        # Spread two points per LGA on a deterministic ring around the centroid.
        for j in range(2):
            angle_deg = (i * 90 + j * 45) % 360
            import math
            rad = math.radians(angle_deg)
            lon = centroid_lon + math.cos(rad) * 0.35
            lat = centroid_lat + math.sin(rad) * 0.25
            out.append(PovertySettlementInput(
                settlement_name=f"{lga} settlement {j + 1}",
                lga=lga, lon=lon, lat=lat,
            ))
    return out


async def ingest_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    viirs_client: BlackMarbleClient,
    worldpop_client: WorldPopClient,
    date: datetime | None = None,
) -> PovertyIngestResult:
    """End-to-end ingest for one tenant. Caller manages the session/commit."""
    if tenant_id not in PILOT_TENANT_IDS:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")

    bbox = PILOT_BBOX.get(tenant_id)
    if bbox is None:
        raise ValueError(f"No bbox for tenant {tenant_id}")

    if date is not None:
        granules = await viirs_client.search_granules(
            bbox=bbox, date=date, max_results=4,
        )
    else:
        start = datetime.now(timezone.utc) - timedelta(days=VIIRS_LATENCY_DAYS)
        _, granules = await _latest_published_viirs_date(viirs_client, bbox, start)
    granule: BlackMarbleGranule | None = granules[0] if granules else None

    layer: WorldPopLayer | None = await worldpop_client.latest_layer_for_tenant(tenant_id)

    # Reuse the seed-village geometry so live rows land on the same LGA
    # centroids as the dashboard's seed rows (no coordinate drift). Only
    # fabricate a synthetic grid when the tenant hasn't been seeded.
    # _seed_settlements() has already set the tenant search_path; the writes
    # below run in the same schema.
    settlements = await _seed_settlements(session, tenant_id)
    if not settlements:
        settlements = settlements_for(tenant_id)
    signals = compose_signals(
        tenant_id=tenant_id,
        settlements=settlements,
        viirs_granule=granule,
        worldpop_layer=layer,
    )

    written = 0
    for sig in signals:
        await _upsert_village(session, tenant_id=tenant_id, sig=sig)
        written += 1

    sources = tuple(sorted({s.source for s in signals}))

    log.info(
        "poverty.ingest tenant=%s granule=%s layer=%s written=%d sources=%s",
        tenant_id,
        granule.granule_id if granule else "<none>",
        layer.dataset_id if layer else "<none>",
        written,
        sources,
    )

    return PovertyIngestResult(
        tenant_id=tenant_id,
        viirs_granule_id=granule.granule_id if granule else None,
        worldpop_dataset_id=layer.dataset_id if layer else None,
        settlements_total=len(settlements),
        rows_written=written,
        sources_observed=sources,
    )


async def _upsert_village(
    session: AsyncSession,
    *,
    tenant_id: str,
    sig: PovertySignal,
) -> None:
    """Replace any prior row for this (lga, settlement_name, source) tuple."""
    await session.execute(
        text(
            """
            DELETE FROM poverty_villages
             WHERE tenant_id        = :tenant_id
               AND lga              = :lga
               AND settlement_name  = :settlement_name
               AND source           = :source
            """
        ),
        {
            "tenant_id": tenant_id,
            "lga": sig.lga,
            "settlement_name": sig.settlement_name,
            "source": sig.source,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO poverty_villages (
                tenant_id, settlement_name, lga, location,
                poverty_score, population, households_unreached,
                nightlight_dimness, has_dhs_data,
                viirs_pixel_radiance, worldpop_estimate,
                source
            ) VALUES (
                :tenant_id, :settlement_name, :lga,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :poverty_score, :population, :hh_unreached,
                :dimness, FALSE,
                :viirs_radiance, :worldpop_estimate,
                :source
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "settlement_name": sig.settlement_name,
            "lga": sig.lga,
            "lon": sig.lon,
            "lat": sig.lat,
            "poverty_score": sig.poverty_score,
            "population": sig.population,
            "hh_unreached": sig.households_unreached,
            "dimness": sig.nightlight_dimness,
            "viirs_radiance": sig.viirs_pixel_radiance,
            "worldpop_estimate": sig.worldpop_estimate,
            "source": sig.source,
        },
    )


async def ingest_all(
    session_factory,
    *,
    viirs_http: httpx.AsyncClient | None = None,
    worldpop_http: httpx.AsyncClient | None = None,
    date: datetime | None = None,
) -> list[PovertyIngestResult]:
    """Run ingest_tenant() for every pilot tenant. Returns per-tenant summaries.

    Used by the CLI runner; production scheduling lives in scheduler.py.
    """
    viirs = BlackMarbleClient(http=viirs_http)
    worldpop = WorldPopClient(http=worldpop_http)
    results: list[PovertyIngestResult] = []
    async with session_factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            result = await ingest_tenant(
                session, tenant_id=tenant_id,
                viirs_client=viirs, worldpop_client=worldpop, date=date,
            )
            results.append(result)
        await session.commit()
    return results
