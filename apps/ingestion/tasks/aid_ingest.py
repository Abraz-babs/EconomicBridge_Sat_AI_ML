"""Aid coordination ingest — Module 02 live data from HDX HAPI.

Reads HAPI operational-presence (who-does-what-where) for a tenant's country
(filtered to its state for Nigerian tenants; whole country for Ghana/Senegal),
registers each humanitarian org in `public.aid_agencies`, and writes one
`aid_coverage` row per (org, LGA) tagged source='hapi_v1'. The coverage view
then derives per-LGA agency counts + gap/duplication exactly as it does for
seed data.

HAPI is keyless. Coverage is real and uneven — populated only where partners
actually operate — so this augments (does not replace) the seed baseline; the
dashboard's `sources[]` shows both.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from sources.hdx_hapi import HapiClient, OrgPresence, slugify

log = logging.getLogger(__name__)


SOURCE_HAPI = "hapi_v1"

# Tenant → HAPI location_code. Nigerian states share NGA (filtered by state);
# the ECOWAS country tenants use their own ISO3 with no admin-1 filter.
TENANT_TO_LOCATION: dict[str, str] = {
    "kebbi": "NGA", "benue": "NGA", "plateau": "NGA", "kaduna": "NGA",
    "niger": "NGA", "zamfara": "NGA", "nasarawa": "NGA", "fct": "NGA",
    "ghana": "GHA", "senegal": "SEN",
}

# Nigerian tenants → HAPI admin1_name (the state). None ⇒ no admin-1 filter
# (country tenants take all admin-2 areas).
TENANT_TO_ADMIN1: dict[str, str | None] = {
    "kebbi": "Kebbi", "benue": "Benue", "plateau": "Plateau",
    "kaduna": "Kaduna", "niger": "Niger", "zamfara": "Zamfara",
    "nasarawa": "Nasarawa", "fct": "Federal Capital Territory",
    "ghana": None, "senegal": None,
}


@dataclass(frozen=True, slots=True)
class AidIngestResult:
    tenant_id: str
    location_code: str
    orgs_found: int
    lgas_covered: int
    coverage_rows: int


@dataclass(frozen=True, slots=True)
class _Agency:
    slug: str
    name: str
    sector: str


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _aggregate(
    presences: list[OrgPresence],
) -> tuple[dict[str, _Agency], dict[tuple[str, str], date | None]]:
    """Collapse presence rows to an agency registry + (slug, lga) coverage.

    An org in one LGA across several sectors yields one coverage row; the most
    recent reference period wins for last_active_at.
    """
    agencies: dict[str, _Agency] = {}
    coverage: dict[tuple[str, str], date | None] = {}
    for p in presences:
        slug = slugify(p.org_acronym or p.org_name)
        agencies[slug] = _Agency(slug=slug, name=p.org_name[:120], sector=p.sector_name[:60])
        key = (slug, p.admin2_name)
        end = _parse_date(p.reference_period_end)
        prev = coverage.get(key, "missing")
        if prev == "missing" or (end is not None and (prev is None or end > prev)):
            coverage[key] = end
    return agencies, coverage


async def ingest_aid_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    client: HapiClient | None = None,
) -> AidIngestResult:
    """Pull HAPI operational presence for one tenant and upsert coverage."""
    location = TENANT_TO_LOCATION.get(tenant_id)
    if not location:
        log.info("aid.hapi tenant=%s skipped — no HAPI location mapping", tenant_id)
        return AidIngestResult(tenant_id, "", 0, 0, 0)

    hapi = client or HapiClient()
    presences = await hapi.fetch_operational_presence(
        location_code=location, admin1_name=TENANT_TO_ADMIN1.get(tenant_id),
    )
    agencies, coverage = _aggregate(presences)
    if not coverage:
        log.info("aid.hapi tenant=%s location=%s no operational presence found",
                 tenant_id, location)
        return AidIngestResult(tenant_id, location, len(agencies), 0, 0)

    await set_tenant_schema(session, tenant_id)
    for ag in agencies.values():
        await session.execute(text(
            """
            INSERT INTO public.aid_agencies (slug, name, sector)
            VALUES (:slug, :name, :sector)
            ON CONFLICT (slug) DO UPDATE
              SET name = EXCLUDED.name, sector = EXCLUDED.sector
            """
        ), {"slug": ag.slug, "name": ag.name, "sector": ag.sector})

    for (slug, lga), last_active in coverage.items():
        await session.execute(text(
            """
            INSERT INTO aid_coverage (
                tenant_id, agency_slug, lga, beneficiaries_served,
                last_active_at, source
            ) VALUES (:tenant_id, :slug, :lga, 0, :last_active, :source)
            ON CONFLICT (agency_slug, lga, source) DO UPDATE
              SET last_active_at = EXCLUDED.last_active_at, updated_at = NOW()
            """
        ), {
            "tenant_id": tenant_id, "slug": slug, "lga": lga,
            "last_active": last_active, "source": SOURCE_HAPI,
        })

    await session.commit()
    lgas = {lga for _, lga in coverage}
    log.info(
        "aid.hapi tenant=%s location=%s orgs=%d lgas=%d coverage_rows=%d",
        tenant_id, location, len(agencies), len(lgas), len(coverage),
    )
    return AidIngestResult(
        tenant_id=tenant_id, location_code=location,
        orgs_found=len(agencies), lgas_covered=len(lgas), coverage_rows=len(coverage),
    )
