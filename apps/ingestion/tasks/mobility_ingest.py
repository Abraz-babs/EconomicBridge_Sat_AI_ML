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
from sources.nbs_stats import MobilityIndicator, NbsStatsClient, source_for_tenant
from sources.worldbank import (
    SOURCE_WORLDBANK,
    TENANT_TO_ISO3,
    WorldBankClient,
    WorldBankError,
    compose_mobility_indicators,
)

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
    await set_tenant_schema(session, tenant_id)
    upserted = await _upsert_indicators(
        session, tenant_id, indicators, lga_coords, date.today(),
    )
    await session.commit()
    log.info(
        "mobility.ingest tenant=%s source=%s lgas=%d upserted=%d mock=%s",
        tenant_id, source, len(lga_coords), upserted, mock,
    )
    return MobilityIngestResult(
        tenant_id=tenant_id, source=source,
        lgas_found=len(lga_coords), rows_upserted=upserted, mock=mock,
    )


async def ingest_mobility_worldbank_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    client: WorldBankClient | None = None,
) -> MobilityIngestResult:
    """Anchor Module 06 to the real World Bank national income figure.

    Fetches GNI per capita (USD for every country; Naira too for Nigeria)
    and disaggregates it to per-LGA estimates tagged source='worldbank_v1',
    reusing the seed_v1 LGA geometry. All pilots are covered — USD is the
    universal anchor (no FX), so Ghana/Senegal land in USD and Nigeria gets
    `₦X ($Y)`. On a World Bank fetch/parse failure we write nothing rather
    than ship a fake row.
    """
    wb = client or WorldBankClient()
    iso3 = TENANT_TO_ISO3.get(tenant_id)
    if iso3 is None:
        log.info("mobility.worldbank tenant=%s skipped — no ISO3 mapping", tenant_id)
        return MobilityIngestResult(
            tenant_id=tenant_id, source=SOURCE_WORLDBANK,
            lgas_found=0, rows_upserted=0, mock=False,
        )

    lga_coords = await _seed_lgas(session, tenant_id)
    if not lga_coords:
        log.warning(
            "mobility.worldbank tenant=%s has no seed_v1 rows — run "
            "scripts.seed_mobility_indicators first", tenant_id,
        )
        return MobilityIngestResult(
            tenant_id=tenant_id, source=SOURCE_WORLDBANK,
            lgas_found=0, rows_upserted=0, mock=False,
        )

    try:
        anchor = await wb.fetch_country_anchor(iso3)
    except WorldBankError as exc:
        log.warning("mobility.worldbank tenant=%s fetch failed: %s", tenant_id, exc)
        return MobilityIngestResult(
            tenant_id=tenant_id, source=SOURCE_WORLDBANK,
            lgas_found=len(lga_coords), rows_upserted=0, mock=False,
        )
    if anchor.gni_per_capita_usd is None:
        log.warning(
            "mobility.worldbank tenant=%s: no USD GNI per capita for %s — skipped",
            tenant_id, iso3,
        )
        return MobilityIngestResult(
            tenant_id=tenant_id, source=SOURCE_WORLDBANK,
            lgas_found=len(lga_coords), rows_upserted=0, mock=False,
        )

    indicators = compose_mobility_indicators(tenant_id, list(lga_coords), anchor)
    observed = date(anchor.gni_usd_year or date.today().year, 1, 1)
    await set_tenant_schema(session, tenant_id)
    upserted = await _upsert_indicators(
        session, tenant_id, indicators, lga_coords, observed,
    )
    await session.commit()
    log.info(
        "mobility.worldbank tenant=%s gni_pc_usd=%.0f year=%s lgas=%d upserted=%d",
        tenant_id, anchor.gni_per_capita_usd, anchor.gni_usd_year,
        len(lga_coords), upserted,
    )
    return MobilityIngestResult(
        tenant_id=tenant_id, source=SOURCE_WORLDBANK,
        lgas_found=len(lga_coords), rows_upserted=upserted, mock=False,
    )


async def _upsert_indicators(
    session: AsyncSession,
    tenant_id: str,
    indicators: list[MobilityIndicator],
    lga_coords: dict[str, tuple[float, float]],
    observed: date,
) -> int:
    """UPSERT one mobility_indicators row per indicator. Caller commits.

    Shared by the NBS/ECOWAS and World Bank ingest paths so the live rows
    land at the seed_v1 LGA geometry with one source-keyed row each.
    """
    upserted = 0
    for ind in indicators:
        lon, lat = lga_coords[ind.lga]
        await session.execute(text(
            """
            INSERT INTO mobility_indicators (
                tenant_id, lga, location,
                cost_of_living_index, avg_household_income_ngn,
                avg_household_income_usd,
                income_opportunity_score, displacement_capacity_index,
                population, observed_at, source
            ) VALUES (
                :tenant_id, :lga,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :col, :income_ngn, :income_usd, :opp, :cap, :pop,
                :observed_at, :source
            )
            ON CONFLICT (tenant_id, lga, source) DO UPDATE SET
                cost_of_living_index        = EXCLUDED.cost_of_living_index,
                avg_household_income_ngn    = EXCLUDED.avg_household_income_ngn,
                avg_household_income_usd    = EXCLUDED.avg_household_income_usd,
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
            "income_ngn": ind.avg_household_income_ngn,
            "income_usd": ind.avg_household_income_usd,
            "opp": ind.income_opportunity_score,
            "cap": ind.displacement_capacity_index,
            "pop": ind.population,
            "observed_at": observed,
            "source": ind.source,
        })
        upserted += 1
    return upserted
