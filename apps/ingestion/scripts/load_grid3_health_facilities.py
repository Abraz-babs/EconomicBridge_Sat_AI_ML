"""Load the GRID3 Nigeria health facility register into public.health_facilities (0059).

The care side of the Mobility Compass: health facilities per 10,000 people in
each LGA, beside the modelled walk to the nearest one. Our own copy, refreshed
a couple of times a year, so the page never depends on a third-party server.

    python -m scripts.load_grid3_health_facilities                 # both releases, 8 pilots
    python -m scripts.load_grid3_health_facilities --release v3.0
    python -m scripts.load_grid3_health_facilities --dry-run       # download + count only

TWO RELEASES, BOTH KEPT
-----------------------
GRID3 v3.0 (updated August 2026) covers 24 states — not Benue or Plateau.
GRID3 v2.0 (November 2024, built on the national Health Facility Registry)
covers all 37. The API reads v3.0 for a state where it exists and v2.0
otherwise, so every LGA in a state is compared on one release. Measured
2026-09-28: v3.0 Kebbi 1,346 · Zamfara 1,181 · Niger 3,316 · Kaduna 2,109 ·
Nasarawa 1,666 · FCT 1,047; v2.0 Benue 2,284 · Plateau 1,643.

Facilities GRID3 lists without coordinates (v3.0: 638 in Niger, 362 in the
FCT) are stored with no point: they count for the state, never for an LGA.

States are stored in the school register's spelling ("Fct" for the capital
territory) so one state name serves both GRID3 registers.

UPSERT, NEVER DELETE: an unchanged refresh writes nothing; a facility GRID3
drops is kept ("no record should go").

Source: GRID3 Nigeria health facilities, CC BY 4.0. Attribution shown
wherever a facility count is displayed.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import httpx
from sqlalchemy import text

from db import get_session_factory

log = logging.getLogger("grid3_health")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

_BASE = "https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services"
PAGE = 2000            # both services' maxRecordCount
ATTEMPTS = 4

# release -> (layer query URL, state field, {GRID3 state spelling: stored state},
#             field map {column: source field}, id field)
RELEASES: dict[str, dict] = {
    "v3.0": {
        "url": f"{_BASE}/GRID3_NGA_health_facility_v3_0/FeatureServer/0/query",
        "state_field": "state_standard",
        "states": {"Kebbi": "Kebbi", "Zamfara": "Zamfara", "Niger": "Niger",
                   "Kaduna": "Kaduna", "Nasarawa": "Nasarawa", "FCT, Abuja": "Fct"},
        "id": "unique_id",
        "fields": {"name": "facility_name", "level": "facility_level", "type": "facility_type",
                   "ownership": "facility_ownership", "functional": "functional",
                   "ward": "ward_standard", "lga": "lga_standard"},
    },
    "v2.0": {
        "url": f"{_BASE}/GRID3_NGA_health_facilities_v2_0/FeatureServer/0/query",
        "state_field": "state",
        "states": {"Kebbi": "Kebbi", "Zamfara": "Zamfara", "Niger": "Niger", "Kaduna": "Kaduna",
                   "Benue": "Benue", "Plateau": "Plateau", "Nasarawa": "Nasarawa", "Fct": "Fct"},
        "id": "globalid",
        "fields": {"name": "facility_name", "level": "facility_level", "type": None,
                   "ownership": "ownership", "functional": None,
                   "ward": "ward", "lga": "lga"},
    },
}

UPSERT = text("""
    INSERT INTO public.health_facilities
        (release, source_id, name, level, type, ownership, functional, ward, lga, state, geom)
    VALUES (:release, :source_id, :name, :level, :type, :ownership, :functional, :ward, :lga,
            :state, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    ON CONFLICT (release, source_id) DO UPDATE SET
        name = EXCLUDED.name, level = EXCLUDED.level, type = EXCLUDED.type,
        ownership = EXCLUDED.ownership, functional = EXCLUDED.functional,
        ward = EXCLUDED.ward, lga = EXCLUDED.lga, state = EXCLUDED.state,
        geom = EXCLUDED.geom, loaded_at = NOW()
    WHERE (health_facilities.name, health_facilities.level, health_facilities.type,
           health_facilities.ownership, health_facilities.functional, health_facilities.ward,
           health_facilities.lga, health_facilities.state, ST_AsBinary(health_facilities.geom))
      IS DISTINCT FROM
          (EXCLUDED.name, EXCLUDED.level, EXCLUDED.type, EXCLUDED.ownership,
           EXCLUDED.functional, EXCLUDED.ward, EXCLUDED.lga, EXCLUDED.state,
           ST_AsBinary(EXCLUDED.geom))
""")


def _clean(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def parse_feature(f: dict, release: str, state: str) -> dict | None:
    """One GRID3 feature -> one upsert row, or None without an id or name.

    A facility with no usable point (GRID3 flags "missing xy coordinates") is
    still a registered facility: it is kept with lon/lat None, so it counts
    for its state but is never placed in an LGA.
    """
    spec = RELEASES[release]
    a, g = f.get("attributes", {}), f.get("geometry") or {}
    sid = _clean(a.get(spec["id"]))
    name = _clean(a.get(spec["fields"]["name"]))
    if not sid or not name:
        return None
    try:
        lon, lat = float(g["x"]), float(g["y"])
    except (KeyError, TypeError, ValueError):
        lon = lat = None
    if lon is not None and not (2.0 <= lon <= 15.5 and 3.5 <= lat <= 14.5):
        lon = lat = None          # a point outside Nigeria is not a location
    row = {"release": release, "source_id": sid, "state": state, "lon": lon, "lat": lat}
    for col, src in spec["fields"].items():
        row[col] = _clean(a.get(src)) if src else None
    return row


async def _page(client: httpx.AsyncClient, release: str, grid3_state: str, offset: int) -> list[dict]:
    spec = RELEASES[release]
    fields = ",".join([spec["id"], *(f for f in spec["fields"].values() if f)])
    params = {
        "where": f"{spec['state_field']}='{grid3_state}'", "outFields": fields,
        "returnGeometry": "true", "outSR": 4326, "f": "json",
        "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": PAGE,
    }
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = await client.get(spec["url"], params=params)
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"])
            return body.get("features", [])
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            if attempt == ATTEMPTS:
                raise
            log.warning("GRID3 health %s %s offset %d failed (%r), retry %d/%d",
                        release, grid3_state, offset, exc, attempt, ATTEMPTS - 1)
            await asyncio.sleep(3 * attempt)
    return []


async def fetch_state(client: httpx.AsyncClient, release: str, grid3_state: str) -> list[dict]:
    stored = RELEASES[release]["states"][grid3_state]
    rows: list[dict] = []
    offset = 0
    while True:
        feats = await _page(client, release, grid3_state, offset)
        rows.extend(r for r in (parse_feature(f, release, stored) for f in feats) if r is not None)
        if len(feats) < PAGE:
            return rows
        offset += PAGE


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", choices=sorted(RELEASES), help="one release (default: both)")
    ap.add_argument("--dry-run", action="store_true", help="download and count, write nothing")
    args = ap.parse_args()
    releases = [args.release] if args.release else list(RELEASES)

    factory = None if args.dry_run else get_session_factory()
    async with httpx.AsyncClient(timeout=90) as client:
        for release in releases:
            for grid3_state in RELEASES[release]["states"]:
                rows = await fetch_state(client, release, grid3_state)
                if args.dry_run:
                    log.info("GRID3 health %s %-10s %6d facilities, %d located (dry run)", release, grid3_state,
                             len(rows), sum(1 for r in rows if r["lon"] is not None))
                    continue
                async with factory() as session:
                    for i in range(0, len(rows), 1000):
                        await session.execute(UPSERT, rows[i:i + 1000])
                    await session.commit()
                log.info("GRID3 health %s %-10s %6d facilities upserted", release, grid3_state, len(rows))
    if not args.dry_run:
        async with factory() as session:
            stored = (await session.execute(text(
                "SELECT release, state, count(*), count(geom) FROM public.health_facilities "
                "GROUP BY 1, 2 ORDER BY 1, 2"))).all()
        for release, state, n, located in stored:
            log.info("GRID3 health stored %s %-9s %6d (%d located)", release, state, n, located)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
