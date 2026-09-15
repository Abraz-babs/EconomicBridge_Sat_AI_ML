"""Real LGA / admin-2 outlines for every pilot — read with the standard library.

Built by scripts/build_lga_boundaries.py from geoBoundaries and keyed exactly
like data/lga_centroids.json; the build refuses to write a file that disagrees.

WHY NO SHAPELY
--------------
The production ingestion image does not carry shapely, and nothing here needs
it. Point-in-polygon is an even-odd ray cast over the GeoJSON rings behind a
bounding-box prefilter; burning an outline onto an image grid is rasterio's job
(sources/open_archive.py). Adding a geometry library to the image for one
containment test would be the wrong trade.

A MISSING FILE IS AN ERROR, NOT AN EMPTY RESULT
-----------------------------------------------
The centroid index is best-effort labelling and degrades to {} on failure. This
file decides which pixels get scanned at all, so "no boundaries" must never be
able to read as "no LGAs to scan".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "lga_boundaries.geojson"


class LgaBoundaryError(RuntimeError):
    """The boundary file is missing, unreadable or empty."""


@dataclass(frozen=True, slots=True)
class LgaBoundary:
    """One LGA's outline in EPSG:4326."""

    tenant: str
    lga: str
    geometry: dict                              # GeoJSON Polygon / MultiPolygon
    bbox: tuple[float, float, float, float]     # lon_min, lat_min, lon_max, lat_max

    def contains(self, lon: float, lat: float) -> bool:
        """True if (lon, lat) falls inside this LGA."""
        b = self.bbox
        if not (b[0] <= lon <= b[2] and b[1] <= lat <= b[3]):
            return False
        return point_in_geometry(self.geometry, lon, lat)


def _polygons(geometry: dict) -> list:
    """A Polygon or MultiPolygon as a list of polygons (each a list of rings)."""
    kind = geometry.get("type")
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"unsupported geometry type {kind!r}")


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    """Even-odd ray cast. The crossing test guarantees yi != yj, so no /0."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            if lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def point_in_geometry(geometry: dict, lon: float, lat: float) -> bool:
    """Inside an outer ring and not inside any of that polygon's holes."""
    for poly in _polygons(geometry):
        if not poly:
            continue
        outer, holes = poly[0], poly[1:]
        if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
            return True
    return False


def _ring_centroid(ring: list) -> tuple[float, float, float]:
    """(signed area, cx, cy) of one closed ring, by the shoelace formula."""
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if a == 0:
        return 0.0, ring[0][0], ring[0][1]
    return a, cx / (6.0 * a), cy / (6.0 * a)


def centroid(geometry: dict) -> tuple[float, float]:
    """Planar, area-weighted centre of mass in lon/lat, holes subtracted.

    The same quantity shapely's `.centroid` returns, and the point
    lga_centroids.json stores — so it is the key-integrity check between the
    two files. It is NOT guaranteed to lie inside the LGA: for a concave
    outline the centre of mass falls in a neighbour, which six pilot LGAs do.
    """
    area = sx = sy = 0.0
    for poly in _polygons(geometry):
        for k, ring in enumerate(poly):
            a, x, y = _ring_centroid(ring)
            w = abs(a) if k == 0 else -abs(a)   # winding is not guaranteed
            area += w
            sx += w * x
            sy += w * y
    if area == 0:
        raise ValueError("geometry has zero area")
    return sx / area, sy / area


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for poly in _polygons(geometry):
        for ring in poly:
            for pt in ring:
                xs.append(pt[0])
                ys.append(pt[1])
    return (min(xs), min(ys), max(xs), max(ys))


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, tuple[LgaBoundary, ...]], dict]:
    try:
        doc = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LgaBoundaryError(f"cannot read LGA boundaries at {DATA_PATH}: {exc}") from exc

    by_tenant: dict[str, list[LgaBoundary]] = {}
    for f in doc.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry")
        if not g or "tenant" not in p or "lga" not in p:
            continue
        by_tenant.setdefault(p["tenant"], []).append(
            LgaBoundary(tenant=p["tenant"], lga=p["lga"], geometry=g, bbox=_bbox(g)))
    if not by_tenant:
        raise LgaBoundaryError(f"no LGA boundaries in {DATA_PATH}")
    return {t: tuple(v) for t, v in by_tenant.items()}, doc.get("metadata") or {}


def tenants() -> list[str]:
    """Every tenant that has boundaries — configured, whether or not active."""
    return sorted(_load()[0])


def for_tenant(tenant: str) -> tuple[LgaBoundary, ...]:
    """All LGA outlines for one tenant; empty for an unknown tenant."""
    return _load()[0].get(tenant, ())


def get(tenant: str, lga: str) -> LgaBoundary | None:
    """One LGA by name, or None."""
    return next((b for b in for_tenant(tenant) if b.lga == lga), None)


def lga_at(tenant: str, lon: float, lat: float) -> LgaBoundary | None:
    """The LGA a point falls in, or None if it is outside every LGA.

    This is what lets a detected hotspot say where it is, instead of every
    detection in an LGA being pinned to the LGA's centre.
    """
    return next((b for b in for_tenant(tenant) if b.contains(lon, lat)), None)


def attribution() -> dict:
    """Licence + source per country, as recorded at build time (CC BY needs it)."""
    return dict(_load()[1].get("attribution") or {})


def concave_lgas() -> set[tuple[str, str]]:
    """(tenant, lga) pairs whose stored centroid lies OUTSIDE the LGA.

    Any feed that samples the centroid is reading a neighbouring LGA for these.
    """
    return {(t, n) for t, n in (_load()[1].get("concave_lgas") or [])}


def clear_cache() -> None:
    """Forget the loaded file (tests, or after a rebuild)."""
    _load.cache_clear()
