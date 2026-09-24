"""Load GRID3 named settlements into public.named_settlements (migration 0052).

The village and ward behind every alert's coordinates, so a field team can
drive to the place an alert names. Our own copy, loaded once and refreshed a
couple of times a year — GRID3 changes rarely (the current release is 2020) —
so an alert never goes out unnamed because GRID3's server is slow or down.

    python -m scripts.load_grid3_settlements                  # the 8 Nigerian pilots
    python -m scripts.load_grid3_settlements --states Kebbi,Fct
    python -m scripts.load_grid3_settlements --dry-run        # download + count only

Measured 2026-09-24: 76,995 villages for the pilots, ~13 MB over 39 pages of
2,000, about 1.5 minutes; ~8 MB stored.

UPSERT, NEVER DELETE. A refresh inserts new villages and updates a row only
when GRID3 actually changed it (the WHERE on the conflict clause), so an
unchanged refresh writes nothing and the retention trigger archives only real
changes. A village GRID3 drops is kept — "no record should go".

Source: GRID3 NGA - Settlement Names, CC BY 4.0. Attribution shown wherever a
name is displayed.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import httpx
from sqlalchemy import text

from db import get_session_factory

log = logging.getLogger("grid3_settlements")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

LAYER = ("https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/"
         "Settlements_in_Nigeria/FeatureServer/0/query")
# GRID3 spells the capital territory "Fct".
PILOT_STATES = ("Kebbi", "Zamfara", "Niger", "Kaduna", "Benue", "Plateau", "Nasarawa", "Fct")
PAGE = 2000            # the service's maxRecordCount
ATTEMPTS = 4

UPSERT = text("""
    INSERT INTO public.named_settlements
        (grid3_id, name, alt_name, ward, lga, state, source, geom)
    VALUES (:gid, :name, :alt, :ward, :lga, :state, :source,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    ON CONFLICT (grid3_id) DO UPDATE SET
        name = EXCLUDED.name, alt_name = EXCLUDED.alt_name, ward = EXCLUDED.ward,
        lga = EXCLUDED.lga, state = EXCLUDED.state, source = EXCLUDED.source,
        geom = EXCLUDED.geom, loaded_at = NOW()
    WHERE (named_settlements.name, named_settlements.alt_name, named_settlements.ward,
           named_settlements.lga, named_settlements.state, named_settlements.source,
           ST_AsBinary(named_settlements.geom))
      IS DISTINCT FROM
          (EXCLUDED.name, EXCLUDED.alt_name, EXCLUDED.ward, EXCLUDED.lga,
           EXCLUDED.state, EXCLUDED.source, ST_AsBinary(EXCLUDED.geom))
""")


def _clean(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


async def _page(client: httpx.AsyncClient, state: str, offset: int) -> list[dict]:
    params = {
        "where": f"statename='{state}'",
        "outFields": "globalid,set_name,set_altnam,wardname,lganame,statename,source",
        "returnGeometry": "true", "outSR": 4326, "f": "json",
        "orderByFields": "FID", "resultOffset": offset, "resultRecordCount": PAGE,
    }
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = await client.get(LAYER, params=params)
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"])
            return body.get("features", [])
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            if attempt == ATTEMPTS:
                raise
            log.warning("GRID3 %s offset %d failed (%r), retry %d/%d",
                        state, offset, exc, attempt, ATTEMPTS - 1)
            await asyncio.sleep(3 * attempt)
    return []


async def fetch_state(client: httpx.AsyncClient, state: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        feats = await _page(client, state, offset)
        for f in feats:
            a, g = f.get("attributes", {}), f.get("geometry") or {}
            name = _clean(a.get("set_name"))
            if not name or a.get("globalid") is None or "x" not in g:
                continue
            rows.append({
                "gid": str(a["globalid"]), "name": name, "alt": _clean(a.get("set_altnam")),
                "ward": _clean(a.get("wardname")), "lga": _clean(a.get("lganame")),
                "state": _clean(a.get("statename")), "source": _clean(a.get("source")),
                "lon": float(g["x"]), "lat": float(g["y"]),
            })
        if len(feats) < PAGE:
            return rows
        offset += PAGE


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", help="comma-separated GRID3 state names (default: pilots)")
    ap.add_argument("--dry-run", action="store_true", help="download and count, write nothing")
    args = ap.parse_args()
    states = [s.strip() for s in args.states.split(",")] if args.states else list(PILOT_STATES)

    # A dry run needs no database — it only proves the download and parsing.
    factory = None if args.dry_run else get_session_factory()
    total = 0
    async with httpx.AsyncClient(timeout=90) as client:
        for state in states:
            rows = await fetch_state(client, state)
            total += len(rows)
            if args.dry_run:
                log.info("GRID3 %-9s %6d named settlements (dry run)", state, len(rows))
                continue
            async with factory() as session:
                for i in range(0, len(rows), 1000):
                    await session.execute(UPSERT, rows[i:i + 1000])
                await session.commit()
            log.info("GRID3 %-9s %6d named settlements upserted", state, len(rows))
    if not args.dry_run:
        async with factory() as session:
            stored = (await session.execute(
                text("SELECT count(*) FROM public.named_settlements"))).scalar()
        log.info("GRID3 done: %d fetched, %d stored in public.named_settlements", total, stored)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
