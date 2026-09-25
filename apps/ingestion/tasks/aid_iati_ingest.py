"""Aid activities from IATI — Module 02 made real (replaces the seed baseline).

For every pilot tenant, takes the IATI activities in implementation for its
country (sources/iati_dportal.py), keeps those current today, and places each
published location:

  * a SITE inside one of the tenant's LGAs  → a row with that LGA;
  * a state-level location for the tenant  → a row with lga = NULL (statewide);
  * a national location                     → nothing for a state tenant (a
    national programme is not activity IN the state); countrywide (NULL) for
    the Ghana / Senegal tenants, which are whole countries.

Rows go to tenant_<id>.aid_activities (migration 0055), one per (activity,
coordinate). They are ADDED and updated in place only when something changed
(the retention triggers archive every earlier version); nothing is deleted —
an activity that ends stays as history, and the API shows only current ones.

    python -m scripts.run_aid_iati --tenant kebbi,fct
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from db import get_session_factory, set_tenant_schema
from sources import lga_boundaries as lb
from sources.hdx_hapi import slugify
from sources.iati_dportal import (
    COUNTRY_TENANTS, SHARED_MIN, STATE_CENTRE_KM, TENANT_COUNTRY, TENANT_STATE,
    DPortalClient, IatiLocation, is_current, is_national, km, named_states,
    sector_buckets, sector_names,
)

log = logging.getLogger(__name__)

SOURCE = "iati_v1"


@dataclass(frozen=True, slots=True)
class PlannedRow:
    iati_id: str
    org_name: str
    org_ref: str | None
    org_slug: str
    title: str | None
    sectors: str
    sector_buckets: tuple[str, ...]
    lga: str | None          # None = statewide / countrywide
    location_name: str | None
    lon: float
    lat: float
    start: date | None
    end: date | None


def state_centre(tenant_id: str) -> tuple[float, float]:
    pts = [lb.centroid(b.geometry) for b in lb.for_tenant(tenant_id)]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def place(tenant_id: str, loc: IatiLocation, centre: tuple[float, float]) -> tuple[bool, str | None]:
    """(belongs to this tenant, LGA or None for tenant-wide). Pure given the boundary file."""
    country_tenant = tenant_id in COUNTRY_TENANTS
    if is_national(loc):
        return (country_tenant, None)
    states = named_states(loc.location_name)
    if states:
        return (TENANT_STATE.get(tenant_id) in states, None)
    b = lb.lga_at(tenant_id, loc.lon, loc.lat)
    if b is None:
        return (False, None)
    if loc.shared >= SHARED_MIN and km((loc.lon, loc.lat), centre) <= STATE_CENTRE_KM:
        return (True, None)
    return (True, b.lga)


def plan_rows(tenant_id: str, locations: list[IatiLocation], today: date) -> list[PlannedRow]:
    centre = state_centre(tenant_id)
    rows: dict[tuple[str, float, float], PlannedRow] = {}
    for loc in locations:
        if not is_current(loc.start, loc.end, today):
            continue
        mine, lga = place(tenant_id, loc, centre)
        if not mine:
            continue
        rows[(loc.iati_id, loc.lon, loc.lat)] = PlannedRow(
            iati_id=loc.iati_id, org_name=loc.org_name, org_ref=loc.org_ref,
            org_slug=slugify(loc.org_ref or loc.org_name, max_len=80),
            title=loc.title, sectors="; ".join(sector_names(loc.sector_groups)),
            sector_buckets=tuple(sector_buckets(loc.sector_groups)),
            lga=lga, location_name=loc.location_name, lon=loc.lon, lat=loc.lat,
            start=loc.start, end=loc.end,
        )
    return list(rows.values())


_UPSERT = text("""
    INSERT INTO aid_activities (
        iati_id, org_name, org_ref, org_slug, title, sectors, sector_buckets,
        lga, location_name, lon, lat, start_date, end_date, source
    ) VALUES (
        :iati_id, :org_name, :org_ref, :org_slug, :title, :sectors, :sector_buckets,
        :lga, :location_name, :lon, :lat, :start, :end, :source
    )
    ON CONFLICT (iati_id, lon, lat) DO UPDATE SET
        org_name = EXCLUDED.org_name, org_ref = EXCLUDED.org_ref,
        org_slug = EXCLUDED.org_slug, title = EXCLUDED.title,
        sectors = EXCLUDED.sectors, sector_buckets = EXCLUDED.sector_buckets,
        lga = EXCLUDED.lga, location_name = EXCLUDED.location_name,
        start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date
    WHERE (aid_activities.org_name, aid_activities.org_ref, aid_activities.title,
           aid_activities.sectors, aid_activities.sector_buckets, aid_activities.lga,
           aid_activities.location_name, aid_activities.start_date, aid_activities.end_date)
          IS DISTINCT FROM
          (EXCLUDED.org_name, EXCLUDED.org_ref, EXCLUDED.title, EXCLUDED.sectors,
           EXCLUDED.sector_buckets, EXCLUDED.lga, EXCLUDED.location_name,
           EXCLUDED.start_date, EXCLUDED.end_date)
""")


async def run_aid_iati_ingest(
    tenants: list[str] | None = None, *, today: date | None = None, write: bool = True,
    client: DPortalClient | None = None,
) -> dict[str, str]:
    """Fetch each country once, then plan + store rows for each of its tenants."""
    today = today or date.today()
    target = tenants or sorted(TENANT_COUNTRY)
    dportal = client or DPortalClient()
    by_country: dict[str, list[IatiLocation]] = {}
    out: dict[str, str] = {}
    factory = get_session_factory() if write else None
    for tenant_id in target:
        country = TENANT_COUNTRY.get(tenant_id)
        if not country:
            out[tenant_id] = "skipped: no IATI country mapping"
            continue
        try:
            if country not in by_country:
                by_country[country] = await dportal.fetch_country(country)
                log.info("aid.iati country=%s locations=%d", country, len(by_country[country]))
            rows = plan_rows(tenant_id, by_country[country], today)
            orgs = {r.org_slug for r in rows}
            lgas = {r.lga for r in rows if r.lga}
            wide = sum(1 for r in rows if r.lga is None)
            summary = (f"{len(rows)} locations, {len({r.iati_id for r in rows})} activities, "
                       f"{len(orgs)} organisations, {len(lgas)} LGAs with a site, {wide} statewide")
            if write and factory is not None:
                async with factory() as session:
                    await set_tenant_schema(session, tenant_id)
                    for r in rows:
                        await session.execute(_UPSERT, {
                            "iati_id": r.iati_id, "org_name": r.org_name, "org_ref": r.org_ref,
                            "org_slug": r.org_slug, "title": r.title, "sectors": r.sectors,
                            "sector_buckets": list(r.sector_buckets), "lga": r.lga,
                            "location_name": r.location_name, "lon": r.lon, "lat": r.lat,
                            "start": r.start, "end": r.end, "source": SOURCE,
                        })
                    await session.commit()
            out[tenant_id] = summary
            log.info("aid.iati tenant=%s %s", tenant_id, summary)
        except Exception as exc:  # noqa: BLE001 — one tenant's failure must not stop the rest
            out[tenant_id] = f"FAILED: {exc!s}"
            log.exception("aid.iati FAILED tenant=%s", tenant_id)
    return out
