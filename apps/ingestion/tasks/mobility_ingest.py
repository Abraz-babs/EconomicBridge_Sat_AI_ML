"""Mobility indicators ingest — Module 06 live swap-in.

Reads each tenant's LGA list (+ coordinates) from its existing
seed_v1 mobility_indicators rows, asks the NBS / ECOWAS STAT client
for cost-of-living + income indicators, and UPSERTs them back into
mobility_indicators tagged source='nbs_col_v1' / 'ecowas_stat_v1'.

The seed_v1 rows are never touched — the dashboard's mobility router
shows whichever sources exist (it already aggregates `sources[]`), so
once a tenant has nbs_col_v1 rows the panel surfaces them alongside
(or instead of) the seed baseline.

Locations are reused from the seed_v1 rows so the live rows land at the
same hand-curated LGA centroids (services/lga_geo.py via the seed) —
no coordinate drift between sources. With no API key the client returns
mock indicators, so this whole path runs in dev and proves the
seed→live transition end-to-end.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from sources.nbs_stats import NbsStatsClient, source_for_tenant

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MobilityIngestResult:
    tenant_id: str
    source: str
    lgas_found: int       # LGAs read from seed_v1
    rows_upserted: int    # nbs_col_v1 / ecowas_stat_v1 rows written
    mock: bool            # True when no API key (synthetic indicators)


async def _seed_lgas(
    session: AsyncSession, tenant_id: str,
) -> dict[str, tuple[float, float]]:
    """LGA → (lon, lat) from the tenant's seed_v1 rows."""
    await set_tenant_schema(session, tenant_id)
    rows = (await session.execute(text(
        "SELECT lga, ST_X(location) AS lon, ST_Y(location) AS lat "
        "FROM mobility_indicators WHERE source = 'seed_v1'"
    ))).mappings().all()
    return {r["lga"]: (float(r["lon"]), float(r["lat"])) for r in rows}


async def ingest_mobility_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    client: NbsStatsClient | None = None,
) -> MobilityIngestResult:
    """Pull NBS/ECOWAS indicators for one tenant and upsert the live rows.

    Caller owns the session. Returns counts for logging / the CLI.
    """
    nbs = client or NbsStatsClient()
    source = source_for_tenant(tenant_id)
    mock = not nbs.configured_for(tenant_id)

    lga_coords = await _seed_lgas(session, tenant_id)
    if not lga_coords:
        log.warning(
            "mobility.ingest tenant=%s has no seed_v1 rows — run "
            "scripts.seed_mobility_indicators first", tenant_id,
        )
        return MobilityIngestResult(
            tenant_id=tenant_id, source=source,
            lgas_found=0, rows_upserted=0, mock=mock,
        )

    indicators = await nbs.fetch_indicators(tenant_id, list(lga_coords))
    observed = date.today()
    await set_tenant_schema(session, tenant_id)

    upserted = 0
    for ind in indicators:
        lon, lat = lga_coords[ind.lga]
        await session.execute(text(
            """
            INSERT INTO mobility_indicators (
                tenant_id, lga, location,
                cost_of_living_index, avg_household_income_ngn,
                income_opportunity_score, displacement_capacity_index,
                population, observed_at, source
            ) VALUES (
                :tenant_id, :lga,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :col, :income, :opp, :cap, :pop, :observed_at, :source
            )
            ON CONFLICT (tenant_id, lga, source) DO UPDATE SET
                cost_of_living_index        = EXCLUDED.cost_of_living_index,
                avg_household_income_ngn    = EXCLUDED.avg_household_income_ngn,
                income_opportunity_score    = EXCLUDED.income_opportunity_score,
                displacement_capacity_index = EXCLUDED.displacement_capacity_index,
                population                  = EXCLUDED.population,
                observed_at                 = EXCLUDED.observed_at,
                updated_at                  = NOW()
            """
        ), {
            "tenant_id": tenant_id, "lga": ind.lga,
            "lon": lon, "lat": lat,
            "col": ind.cost_of_living_index,
            "income": ind.avg_household_income_ngn,
            "opp": ind.income_opportunity_score,
            "cap": ind.displacement_capacity_index,
            "pop": ind.population,
            "observed_at": observed,
            "source": ind.source,
        })
        upserted += 1

    await session.commit()
    log.info(
        "mobility.ingest tenant=%s source=%s lgas=%d upserted=%d mock=%s",
        tenant_id, source, len(lga_coords), upserted, mock,
    )
    return MobilityIngestResult(
        tenant_id=tenant_id, source=source,
        lgas_found=len(lga_coords), rows_upserted=upserted, mock=mock,
    )
