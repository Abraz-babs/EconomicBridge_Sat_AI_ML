"""Export simplified LGA outlines for the browser (dev-time; needs shapely).

The ingestion service reads full-precision outlines (data/lga_boundaries.geojson,
built by build_lga_boundaries.py and keyed to our own LGA names). A map only
needs them at screen precision, so this writes a simplified copy into the
frontend's public folder. It adds a file; it never rewrites the Nigerian one
(public/geo/lga-boundaries-ng.json) that existing module maps read.

    apps/api/.venv/Scripts/python.exe apps/ingestion/scripts/export_lga_outlines.py \
        --tenants ghana senegal --out apps/frontend/public/geo/lga-boundaries-gh-sn.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import mapping, shape

SRC = Path(__file__).resolve().parents[1] / "data" / "lga_boundaries.geojson"
TOLERANCE_DEG = 0.004       # ~400 m: invisible at state zoom, a fraction of the file size
DECIMALS = 4                # ~11 m


def _round(coords: object) -> object:
    if isinstance(coords, (int, float)):
        return round(float(coords), DECIMALS)
    return [_round(c) for c in coords]  # type: ignore[union-attr]


def main() -> None:
    """Write the simplified FeatureCollection for the requested tenants."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenants", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    doc = json.loads(SRC.read_text(encoding="utf-8"))
    countries = {doc["metadata"]["tenant_country"][t] for t in args.tenants}
    attribution = " · ".join(
        f"{c}: {a['source']} via geoBoundaries ({a['licence'].split('(')[-1].rstrip(')')})"
        for c, a in sorted(doc["metadata"]["attribution"].items()) if c in countries)
    features = []
    for f in doc["features"]:
        p = f["properties"]
        if p["tenant"] not in args.tenants:
            continue
        geom = shape(f["geometry"]).simplify(TOLERANCE_DEG, preserve_topology=True)
        g = mapping(geom)
        features.append({"type": "Feature", "properties": {"tenant": p["tenant"], "lga": p["lga"]},
                         "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}})
    args.out.write_text(json.dumps({"type": "FeatureCollection", "attribution": attribution,
                                    "features": features}, separators=(",", ":")), encoding="utf-8")
    print(f"{len(features)} outlines -> {args.out} ({args.out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
