"""Load the GRID3 school register into public.school_register (migration 0057).

The school side of SkillsBridge's reach list: every mapped school, joined at
request time to the village-light layer (which villages within 2 km show light
at night, and the people living there). Our own copy, refreshed a couple of
times a year — GRID3's school release is 2020 — so the list never depends on
a third-party server being up.

    python -m scripts.load_grid3_schools                  # the 8 Nigerian pilots
    python -m scripts.load_grid3_schools --states Kebbi,Fct
    python -m scripts.load_grid3_schools --dry-run        # download + count only

Measured 2026-09-27: 24,127 schools for the pilots (Kebbi 2,075), 15 pages of
2,000.

UPSERT, NEVER DELETE. A refresh updates a row only when GRID3 actually changed
it, so an unchanged refresh writes nothing and the retention trigger archives
only real changes. A school GRID3 drops is kept — "no record should go".

Source: GRID3 NGA Schools with LGA names, CC BY 4.0. Attribution shown
wherever a school is displayed.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from db import get_session_factory

log = logging.getLogger("grid3_schools")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

LAYER = ("https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/"
         "GRID3_Nigeria_Schools_with_LGA_Names/FeatureServer/45/query")
# GRID3 spells the capital territory "Fct", as in the settlement layer.
PILOT_STATES = ("Kebbi", "Zamfara", "Niger", "Kaduna", "Benue", "Plateau", "Nasarawa", "Fct")
PAGE = 2000            # the service's maxRecordCount
ATTEMPTS = 4
FIELDS = ("globalid,name,category,management,education,wardcode,lga_name,state_name,"
          "no_of_stud,no_of_teac,source,timestamp")

UPSERT = text("""
    INSERT INTO public.school_register
        (grid3_id, name, category, management, education, ward_code, lga, state,
         students, teachers, source, surveyed_at, geom)
    VALUES (:gid, :name, :category, :management, :education, :ward_code, :lga, :state,
            :students, :teachers, :source, :surveyed_at,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    ON CONFLICT (grid3_id) DO UPDATE SET
        name = EXCLUDED.name, category = EXCLUDED.category,
        management = EXCLUDED.management, education = EXCLUDED.education,
        ward_code = EXCLUDED.ward_code, lga = EXCLUDED.lga, state = EXCLUDED.state,
        students = EXCLUDED.students, teachers = EXCLUDED.teachers,
        source = EXCLUDED.source, surveyed_at = EXCLUDED.surveyed_at,
        geom = EXCLUDED.geom, loaded_at = NOW()
    WHERE (school_register.name, school_register.category, school_register.management,
           school_register.education, school_register.ward_code, school_register.lga,
           school_register.state, school_register.students, school_register.teachers,
           school_register.source, school_register.surveyed_at,
           ST_AsBinary(school_register.geom))
      IS DISTINCT FROM
          (EXCLUDED.name, EXCLUDED.category, EXCLUDED.management, EXCLUDED.education,
           EXCLUDED.ward_code, EXCLUDED.lga, EXCLUDED.state, EXCLUDED.students,
           EXCLUDED.teachers, EXCLUDED.source, EXCLUDED.surveyed_at,
           ST_AsBinary(EXCLUDED.geom))
""")


def _clean(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _count(v: object) -> int | None:
    """GRID3 writes 0 where a count was never collected; store that as unknown."""
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_feature(f: dict) -> dict | None:
    """One GRID3 feature -> one upsert row, or None when it has no name or point."""
    a, g = f.get("attributes", {}), f.get("geometry") or {}
    name = _clean(a.get("name"))
    if not name or a.get("globalid") is None or "x" not in g or "y" not in g:
        return None
    ts = a.get("timestamp")
    surveyed = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
                if isinstance(ts, (int, float)) and ts > 0 else None)
    return {
        "gid": str(a["globalid"]), "name": name,
        "category": _clean(a.get("category")), "management": _clean(a.get("management")),
        "education": _clean(a.get("education")), "ward_code": _clean(a.get("wardcode")),
        "lga": _clean(a.get("lga_name")), "state": _clean(a.get("state_name")),
        "students": _count(a.get("no_of_stud")), "teachers": _count(a.get("no_of_teac")),
        "source": _clean(a.get("source")), "surveyed_at": surveyed,
        "lon": float(g["x"]), "lat": float(g["y"]),
    }


async def _page(client: httpx.AsyncClient, state: str, offset: int) -> list[dict]:
    params = {
        "where": f"state_name='{state}'", "outFields": FIELDS,
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
            log.warning("GRID3 schools %s offset %d failed (%r), retry %d/%d",
                        state, offset, exc, attempt, ATTEMPTS - 1)
            await asyncio.sleep(3 * attempt)
    return []


async def fetch_state(client: httpx.AsyncClient, state: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        feats = await _page(client, state, offset)
        rows.extend(r for r in (parse_feature(f) for f in feats) if r is not None)
        if len(feats) < PAGE:
            return rows
        offset += PAGE


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", help="comma-separated GRID3 state names (default: pilots)")
    ap.add_argument("--dry-run", action="store_true", help="download and count, write nothing")
    args = ap.parse_args()
    states = [s.strip() for s in args.states.split(",")] if args.states else list(PILOT_STATES)

    factory = None if args.dry_run else get_session_factory()
    total = 0
    async with httpx.AsyncClient(timeout=90) as client:
        for state in states:
            rows = await fetch_state(client, state)
            total += len(rows)
            if args.dry_run:
                log.info("GRID3 %-9s %6d schools (dry run)", state, len(rows))
                continue
            async with factory() as session:
                for i in range(0, len(rows), 1000):
                    await session.execute(UPSERT, rows[i:i + 1000])
                await session.commit()
            log.info("GRID3 %-9s %6d schools upserted", state, len(rows))
    if not args.dry_run:
        async with factory() as session:
            stored = (await session.execute(
                text("SELECT count(*) FROM public.school_register"))).scalar()
        log.info("GRID3 done: %d fetched, %d stored in public.school_register", total, stored)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
