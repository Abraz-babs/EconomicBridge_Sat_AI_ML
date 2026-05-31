"""Build the full real LGA/admin-2 centroid dataset for every pilot tenant.

Replaces the hand-curated 8-LGAs-per-state stand-in with the REAL complete
admin-2 set from geoBoundaries (open data): all 774 Nigerian LGAs, plus
Ghana + Senegal districts. Each unit gets a polygon centroid.

Nigerian LGAs carry no parent-state field in geoBoundaries, so we assign each
LGA to its pilot STATE by point-in-polygon against the ADM1 (state) boundary.
Ghana/Senegal are country tenants → all their ADM2 units map to that tenant.

Output: apps/ingestion/data/lga_centroids.json
    { "<tenant>": [ {"lga": "...", "lon": ..., "lat": ...}, ... ], ... }

Run (needs shapely + httpx):
    python -m scripts.build_lga_centroids
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GEOB = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{lvl}/"
OUT = Path(__file__).resolve().parent.parent / "data" / "lga_centroids.json"

# Pilot Nigerian states → their geoBoundaries ADM1 shapeName.
NG_STATE_NAME = {
    "kebbi": "Kebbi", "benue": "Benue", "plateau": "Plateau", "kaduna": "Kaduna",
    "niger": "Niger", "zamfara": "Zamfara", "nasarawa": "Nasarawa",
    "fct": "Abuja Federal Capital Territory",
}
# ECOWAS country tenants → ISO3 (all that country's ADM2 maps to the tenant).
COUNTRY_TENANT = {"ghana": "GHA", "senegal": "SEN"}


def _fetch_geojson(iso: str, lvl: str) -> dict:
    meta = httpx.get(GEOB.format(iso=iso, lvl=lvl), timeout=60).json()
    url = meta.get("simplifiedGeometryGeoJSON") or meta["gjDownloadURL"]
    log.info("fetching %s %s …", iso, lvl)
    return httpx.get(url, timeout=180, follow_redirects=True).json()


def _centroid(geom: dict) -> tuple[float, float]:
    c = shape(geom).centroid
    return round(c.x, 5), round(c.y, 5)


def build() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}

    # ── Nigeria: assign 774 ADM2 LGAs to pilot states by point-in-polygon ──
    adm1 = _fetch_geojson("NGA", "ADM1")
    state_polys = {}
    for f in adm1["features"]:
        name = f["properties"]["shapeName"]
        for tenant, sname in NG_STATE_NAME.items():
            if name.strip().lower() == sname.lower():
                state_polys[tenant] = shape(f["geometry"])
    missing = set(NG_STATE_NAME) - set(state_polys)
    if missing:
        log.warning("ADM1 names not matched for: %s", missing)
    for t in state_polys:
        out[t] = []

    adm2 = _fetch_geojson("NGA", "ADM2")
    for f in adm2["features"]:
        geom = shape(f["geometry"])
        c = geom.centroid
        for tenant, poly in state_polys.items():
            if poly.contains(c):
                out[tenant].append(
                    {"lga": f["properties"]["shapeName"], "lon": round(c.x, 5), "lat": round(c.y, 5)}
                )
                break

    # ── Ghana / Senegal: every ADM2 district → the country tenant ──
    for tenant, iso in COUNTRY_TENANT.items():
        gj = _fetch_geojson(iso, "ADM2")
        out[tenant] = []
        for f in gj["features"]:
            lon, lat = _centroid(f["geometry"])
            out[tenant].append({"lga": f["properties"]["shapeName"], "lon": lon, "lat": lat})

    return out


def main() -> int:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("wrote %s", OUT)
    for tenant, rows in sorted(data.items()):
        log.info("  %-10s %d units", tenant, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
