"""Build the real LGA / admin-2 BOUNDARY polygons for every pilot tenant.

WHY
---
Until now every per-LGA sweep measured ONE 3 x 3 km square at the LGA's
centroid. Measured against these same boundaries on 2026-09-15 that is 4,023
km2 of the 715,731 km2 the 447 pilot LGAs actually cover — 0.56% of the land
the dashboard calls "per-LGA". A clearing anywhere else in an LGA was
invisible, which is why the same centroids kept resurfacing: they were the
only places ever looked at.

Whole-LGA change detection needs the real outline of each LGA, both to know
which pixels to read and to say which LGA a detected hotspot falls in.

CONSISTENCY WITH lga_centroids.json IS ENFORCED, NOT HOPED FOR
---------------------------------------------------------------
State assignment, naming and the geoBoundaries source are imported from
scripts/build_lga_centroids.py rather than re-implemented, so a boundary and
its centroid can never be keyed by two different rules. The build then
verifies the (tenant, lga) multiset matches the centroid file exactly and that
every centroid falls inside its own polygon, and refuses to write the file if
either check fails — a boundary set that disagrees with the centroids the rest
of the platform uses would silently misattribute detections.

LICENCE
-------
Attribution is read from the geoBoundaries metadata at build time and stored
in the file, so it stays truthful if a source changes. As of 2026-09-15:
Nigeria = GRID3 (CC BY 4.0), Ghana = USAID Ghana HPNO / Ghana Statistical
Service (CC BY 4.0), Senegal = Government of Senegal / OCHA ROWCA
(CC BY 3.0 IGO). All permit commercial use with attribution.

Output: apps/ingestion/data/lga_boundaries.geojson

Run locally (needs shapely + httpx; the production image needs neither —
it reads this file with the standard library and rasterio):
    python -m scripts.build_lga_boundaries
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from shapely.geometry import Point, shape

from scripts.build_lga_centroids import (
    COUNTRY_TENANT,
    GEOB,
    NG_STATE_NAME,
    OUT as CENTROIDS_PATH,
    _fetch_geojson,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUT = Path(__file__).resolve().parent.parent / "data" / "lga_boundaries.geojson"

# ~1 m at the equator. The source geometry is already simplified; carrying
# full float precision would roughly triple the file for no measurable gain.
COORD_DECIMALS = 5

# Which country each tenant's boundaries come from, for attribution.
TENANT_ISO = {**{t: "NGA" for t in NG_STATE_NAME}, **COUNTRY_TENANT}


def _round(coords: object) -> object:
    """Round every coordinate in a (Multi)Polygon coordinate tree."""
    if isinstance(coords, (list, tuple)):
        if coords and isinstance(coords[0], (int, float)):
            return [round(float(c), COORD_DECIMALS) for c in coords]
        return [_round(c) for c in coords]
    return coords


def _attribution(iso: str) -> dict:
    """Licence and source for one country, straight from geoBoundaries."""
    meta = httpx.get(GEOB.format(iso=iso, lvl="ADM2"), timeout=60).json()
    return {
        "source": meta.get("boundarySource"),
        "licence": meta.get("boundaryLicense"),
        "licence_source": meta.get("licenseSource"),
        "year_represented": meta.get("boundaryYearRepresented"),
        "via": "geoBoundaries gbOpen ADM2 (https://www.geoboundaries.org)",
    }


def _feature(tenant: str, lga: str, geom: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"tenant": tenant, "lga": lga},
        "geometry": {"type": geom["type"], "coordinates": _round(geom["coordinates"])},
    }


def build() -> list[dict]:
    """Every pilot LGA as a GeoJSON Feature, keyed exactly like the centroids."""
    features: list[dict] = []

    # Nigeria: same point-in-state rule as build_lga_centroids, on the same
    # geometry centroid, so assignment cannot drift between the two files.
    adm1 = _fetch_geojson("NGA", "ADM1")
    state_polys = {}
    for f in adm1["features"]:
        name = f["properties"]["shapeName"].strip().lower()
        for tenant, sname in NG_STATE_NAME.items():
            if name == sname.lower():
                state_polys[tenant] = shape(f["geometry"])
    missing = set(NG_STATE_NAME) - set(state_polys)
    if missing:
        raise SystemExit(f"ADM1 state names not matched: {sorted(missing)}")

    adm2 = _fetch_geojson("NGA", "ADM2")
    for f in adm2["features"]:
        c = shape(f["geometry"]).centroid
        for tenant, poly in state_polys.items():
            if poly.contains(c):
                features.append(_feature(tenant, f["properties"]["shapeName"], f["geometry"]))
                break

    for tenant, iso in COUNTRY_TENANT.items():
        for f in _fetch_geojson(iso, "ADM2")["features"]:
            features.append(_feature(tenant, f["properties"]["shapeName"], f["geometry"]))

    return features


# A stored centroid is "its boundary's own centre" if it lies within this many
# degrees (~55 m) of that polygon's centre of mass. Both sides are rounded to
# 5 decimals, so genuine matches differ by well under 1e-4.
CENTRE_TOLERANCE_DEG = 5e-4


def verify(features: list[dict]) -> tuple[list[str], list[list[str]]]:
    """(problems that must block the write, concave LGAs to record).

    Two different questions, deliberately kept apart:

    * KEY INTEGRITY — is each stored centroid the centre of mass of the polygon
      stored under the same (tenant, lga)? A failure means a naming or state
      assignment mismatch, and the file must not ship.
    * CONCAVITY — does that centre fall inside the LGA? For a crescent- or
      hook-shaped LGA the centre of mass lies OUTSIDE it, in a neighbour. That
      is a defect of the centroid, not of the boundary: found 2026-09-15 for
      six pilot LGAs (e.g. Bungudu's centre sits in Gusau, 10.5 km from any
      point of Bungudu), meaning every centroid-sampled feed has been reading
      the neighbouring LGA there. Recorded, not blocked — whole-LGA reads scan
      the real outline and are unaffected.
    """
    problems: list[str] = []
    centroids = json.loads(CENTROIDS_PATH.read_text(encoding="utf-8"))

    want = Counter((t, g["lga"]) for t, rows in centroids.items() for g in rows)
    have = Counter((f["properties"]["tenant"], f["properties"]["lga"]) for f in features)
    for key in sorted((want - have).keys()):
        problems.append(f"centroid has no boundary: {key}")
    for key in sorted((have - want).keys()):
        problems.append(f"boundary has no centroid: {key}")

    by_key: dict[tuple[str, str], list] = {}
    for f in features:
        k = (f["properties"]["tenant"], f["properties"]["lga"])
        by_key.setdefault(k, []).append(shape(f["geometry"]))

    concave: list[list[str]] = []
    for tenant, rows in centroids.items():
        for g in rows:
            polys = by_key.get((tenant, g["lga"]), [])
            if not polys:
                continue            # already reported as "has no boundary"
            stored = Point(g["lon"], g["lat"])
            if not any(p.centroid.distance(stored) < CENTRE_TOLERANCE_DEG for p in polys):
                problems.append(f"centroid is not its boundary's centre: ({tenant}, {g['lga']})")
            elif not any(p.contains(stored) for p in polys):
                concave.append([tenant, g["lga"]])

    for tenant, lga in concave:
        log.warning("concave LGA — stored centre lies OUTSIDE it, in a neighbour: "
                    "(%s, %s). Centroid-sampled feeds read the wrong LGA here.", tenant, lga)
    log.info("verify: %d features, %d centroids, %d key problems, %d concave",
             len(features), sum(want.values()), len(problems), len(concave))
    return problems, concave


def main() -> int:
    features = build()
    problems, concave = verify(features)
    if problems:
        for p in problems[:40]:
            log.error("  %s", p)
        log.error("refusing to write %s: %d problem(s)", OUT, len(problems))
        return 1

    doc = {
        "type": "FeatureCollection",
        "metadata": {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "builder": "apps/ingestion/scripts/build_lga_boundaries.py",
            "coord_decimals": COORD_DECIMALS,
            "attribution": {iso: _attribution(iso) for iso in sorted(set(TENANT_ISO.values()))},
            "tenant_country": TENANT_ISO,
            # LGAs whose stored centroid lies outside the LGA itself. Whole-LGA
            # reads are unaffected; anything sampling the centroid is not.
            "concave_lgas": concave,
        },
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts = Counter(f["properties"]["tenant"] for f in features)
    log.info("wrote %s (%.1f MB)", OUT, OUT.stat().st_size / 1e6)
    for tenant, n in sorted(counts.items()):
        log.info("  %-10s %d LGAs", tenant, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
