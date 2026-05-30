"""SkillsBridge indicators ingest — Module 07 live swap-in.

Reads each tenant's LGA list (+ coordinates) from its seed_v1
skills_indicators rows, asks the GIGA/ITU client for education-access
indicators, and UPSERTs them tagged source='giga_v1'. seed_v1 rows are
left intact; the skills router's source-preference dedup surfaces the
live source when present (mirrors Module 06 / Slice 21).

Locations reuse the seed_v1 coordinates (hand-curated lga_geo centroids)
so live + seed rows for an LGA share the same point.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from sources.giga_itu_stats import GigaItuStatsClient
from sources.worldbank import TENANT_TO_ISO3, WorldBankClient, WorldBankError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkillsIngestResult:
    tenant_id: str
    source: str
    lgas_found: int
    rows_upserted: int
    mock: bool


async def _seed_lgas(
    session: AsyncSession, tenant_id: str,
) -> dict[str, tuple[float, float]]:
    await set_tenant_schema(session, tenant_id)
    rows = (await session.execute(text(
        "SELECT lga, ST_X(location) AS lon, ST_Y(location) AS lat "
        "FROM skills_indicators WHERE source = 'seed_v1'"
    ))).mappings().all()
    return {r["lga"]: (float(r["lon"]), float(r["lat"])) for r in rows}


async def ingest_skills_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    client: GigaItuStatsClient | None = None,
    worldbank: WorldBankClient | None = None,
) -> SkillsIngestResult:
    """Pull GIGA school counts + World Bank ICT connectivity and upsert rows.

    School counts come from live GIGA; connectivity (internet/mobile) is
    anchored to the real World Bank national ICT figures — the commercial-safe
    alternative to ITU. Both keyless/keyed external sources; mock when no GIGA.
    """
    giga = client or GigaItuStatsClient()
    mock = not giga.configured

    lga_coords = await _seed_lgas(session, tenant_id)
    if not lga_coords:
        log.warning(
            "skills.ingest tenant=%s has no seed_v1 rows — run "
            "scripts.seed_skills_indicators first", tenant_id,
        )
        return SkillsIngestResult(
            tenant_id=tenant_id, source="giga_v1",
            lgas_found=0, rows_upserted=0, mock=mock,
        )

    # Real connectivity anchor from World Bank ICT (only on the live path).
    net_pct = mob_pct = None
    if not mock:
        iso3 = TENANT_TO_ISO3.get(tenant_id)
        if iso3:
            try:
                net_pct, mob_pct = await (worldbank or WorldBankClient()).fetch_ict(iso3)
            except WorldBankError as exc:
                log.warning("skills.ingest WB ICT degraded for %s: %s", tenant_id, exc)

    indicators = await giga.fetch_indicators(
        tenant_id, lga_coords,
        national_internet_pct=net_pct, national_mobile_pct=mob_pct,
    )
    observed = date.today()
    await set_tenant_schema(session, tenant_id)

    upserted = 0
    for ind in indicators:
        lon, lat = lga_coords[ind.lga]
        await session.execute(text(
            """
            INSERT INTO skills_indicators (
                tenant_id, lga, location,
                school_count, school_density_per_10k,
                internet_coverage_pct, mobile_coverage_pct,
                electricity_reliability, youth_population,
                learning_gap_index, observed_at, source
            ) VALUES (
                :tenant_id, :lga,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :school_count, :density, :net_pct, :mob_pct,
                :power, :youth_pop, :gap, :observed_at, :source
            )
            ON CONFLICT (tenant_id, lga, source) DO UPDATE SET
                school_count            = EXCLUDED.school_count,
                school_density_per_10k  = EXCLUDED.school_density_per_10k,
                internet_coverage_pct   = EXCLUDED.internet_coverage_pct,
                mobile_coverage_pct     = EXCLUDED.mobile_coverage_pct,
                electricity_reliability = EXCLUDED.electricity_reliability,
                youth_population        = EXCLUDED.youth_population,
                learning_gap_index      = EXCLUDED.learning_gap_index,
                observed_at             = EXCLUDED.observed_at,
                updated_at              = NOW()
            """
        ), {
            "tenant_id": tenant_id, "lga": ind.lga,
            "lon": lon, "lat": lat,
            "school_count": ind.school_count,
            "density": ind.school_density_per_10k,
            "net_pct": ind.internet_coverage_pct,
            "mob_pct": ind.mobile_coverage_pct,
            "power": ind.electricity_reliability,
            "youth_pop": ind.youth_population,
            "gap": ind.learning_gap_index,
            "observed_at": observed,
            "source": ind.source,
        })
        upserted += 1

    await session.commit()
    log.info(
        "skills.ingest tenant=%s source=giga_v1 lgas=%d upserted=%d mock=%s",
        tenant_id, len(lga_coords), upserted, mock,
    )
    return SkillsIngestResult(
        tenant_id=tenant_id, source="giga_v1",
        lgas_found=len(lga_coords), rows_upserted=upserted, mock=mock,
    )
