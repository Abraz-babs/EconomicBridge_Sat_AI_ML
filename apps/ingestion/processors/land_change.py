"""Land-change hotspots from peak wet-season greenness. Pure, no I/O.

WHY THIS SHAPE, AND NOT THE OBVIOUS ONE
---------------------------------------
Four detector designs were tried on real Sentinel data over Jega, Birnin Kebbi
and Bungudu, and every candidate detection was checked by eye against
true-colour imagery (2026-09-15):

    wet-season radar change      0 real of 6   — floodplain, rice, ponds
    dry-season optical + radar   1 real of 17  — fadama irrigation, burn scars
    STOPPED GREENING             8 real of 9   — a new road, construction pads
    BECAME BARE (stricter)       3-4 real of 5 — same road, a graded site

Change is everywhere in this landscape and nearly all of it is farming, water
and fire. What separates permanent conversion from the seasonal cycle is
simple: crops green up again, burn scars regrow, floods recede — a road or a
building never greens again. So the question asked here is only ever

    "was this ground green at the peak of last rainy season, and not at the
     peak of this one?"

against the SAME calendar window in both years, because the year given more
weeks has more chances to reach its peak.

WHAT A HOTSPOT IS NOT
---------------------
It is a measured change in greenness at a place, nothing more. It is not proof
of encroachment, ownership, legality or intent, and the word "encroachment"
must not be attached to one of these rows without a person looking at the
imagery. The 0-of-11 Kebbi flood backtest is what that mistake costs.

KNOWN BLIND SPOT
----------------
Ground that was ALREADY bare cannot "stop greening", so a new building on bare
land is invisible here — verified on a real roadside structure near Birnin
Kebbi (peak 0.36 -> 0.05, missed by both rules). That change is a brightness
change and needs the radar channel; it is not a threshold that can be tuned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from rasterio.features import shapes

from sources.lga_boundaries import centroid as _polygon_centroid

# Peak greenness last season for land to count as having been vegetated.
GREEN_PREV = 0.50
# Peak greenness this season below which it counts as no longer greening.
BARE_NOW = 0.30

# The stricter pair: ground that greened at all last season and is now
# effectively non-vegetated. The lower bound excludes water, which goes
# negative — a reservoir edge that dried is not a new building.
SPARSE_PREV = 0.30
NONVEG_MIN = 0.0
NONVEG_MAX = 0.12

# A pixel needs this many cloud-free looks in BOTH seasons before its peak is
# comparable. Fewer and "not green this year" may just mean "not seen".
MIN_OBSERVATIONS = 3

# Smallest cluster reported. Below ~1 ha at 30 m (about 11 pixels) speckle and
# field-edge slivers dominate.
MIN_HA = 1.0

KIND_STOPPED = "stopped_greening"
KIND_BARE = "became_bare"


@dataclass(frozen=True, slots=True)
class Hotspot:
    """One contiguous patch of ground that stopped greening."""

    kind: str
    lon: float
    lat: float
    area_ha: float
    peak_prev: float
    peak_now: float


def usable(inside: np.ndarray, prev: np.ndarray, now: np.ndarray,
           n_prev: np.ndarray, n_now: np.ndarray) -> np.ndarray:
    """Pixels inside the LGA that both seasons actually saw often enough."""
    return (inside & np.isfinite(prev) & np.isfinite(now)
            & (n_prev >= MIN_OBSERVATIONS) & (n_now >= MIN_OBSERVATIONS))


def stopped_greening(prev: np.ndarray, now: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Was green at last season's peak, is not at this one's."""
    return ok & (prev >= GREEN_PREV) & (now <= BARE_NOW)


def became_bare(prev: np.ndarray, now: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Greened at all last season, now effectively non-vegetated (not water)."""
    return ok & (prev >= SPARSE_PREV) & (now >= NONVEG_MIN) & (now <= NONVEG_MAX)


def _ring_area(ring: list) -> float:
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2.0


def polygon_area_m2(geom: dict) -> float:
    """Area of a projected-CRS polygon, holes subtracted."""
    rings = geom["coordinates"]
    return _ring_area(rings[0]) - sum(_ring_area(r) for r in rings[1:])


def _window(transform, geom: dict, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    xs: list[float] = []
    ys: list[float] = []
    for ring in geom["coordinates"]:
        for x, y in ring:
            xs.append(x)
            ys.append(y)
    res_x, res_y = transform.a, -transform.e
    c0 = max(0, int((min(xs) - transform.c) // res_x))
    c1 = min(shape[1], int((max(xs) - transform.c) // res_x) + 1)
    r0 = max(0, int((transform.f - max(ys)) // res_y))
    r1 = min(shape[0], int((transform.f - min(ys)) // res_y) + 1)
    return r0, max(r1, r0 + 1), c0, max(c1, c0 + 1)


def _median_in(values: np.ndarray, sub: np.ndarray) -> float:
    picked = values[sub & np.isfinite(values)]
    return float(np.median(picked)) if picked.size else float("nan")


def find_hotspots(
    mask: np.ndarray,
    *,
    kind: str,
    transform,
    to_lonlat: Callable[[float, float], tuple[float, float]],
    prev: np.ndarray,
    now: np.ndarray,
    min_ha: float = MIN_HA,
) -> list[Hotspot]:
    """Contiguous patches of `mask`, largest first, each with its own position.

    The position is the patch's own centre — not the LGA's. Reporting every
    detection at the LGA centroid is exactly the defect this replaces.
    """
    out: list[Hotspot] = []
    for geom, _ in shapes(mask.astype("uint8"), mask=mask, transform=transform):
        area_ha = polygon_area_m2(geom) / 10_000.0
        if area_ha < min_ha:
            continue
        cx, cy = _polygon_centroid(geom)
        lon, lat = to_lonlat(cx, cy)
        r0, r1, c0, c1 = _window(transform, geom, mask.shape)
        sub = mask[r0:r1, c0:c1]
        out.append(Hotspot(
            kind=kind,
            lon=round(lon, 5), lat=round(lat, 5),
            area_ha=round(area_ha, 2),
            peak_prev=round(_median_in(prev[r0:r1, c0:c1], sub), 3),
            peak_now=round(_median_in(now[r0:r1, c0:c1], sub), 3),
        ))
    return sorted(out, key=lambda h: h.area_ha, reverse=True)
