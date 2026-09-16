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

# At its seasonal PEAK, land reads above zero. A pixel whose highest greenness
# all season is still negative is open water. Cropland that became a pond, or a
# reservoir that rose, is not encroachment — and given this platform's history
# with floods it must never be filed as though it were. Both rules carry this
# floor; only became_bare did at first, and Kaduna's single detection in the
# first Nigeria-wide pass was exactly this: peak 0.68 -> -0.18.
WATER_PEAK_MAX = 0.0

# The stricter pair: ground that greened at all last season and is now
# effectively non-vegetated.
SPARSE_PREV = 0.30
NONVEG_MAX = 0.12

# A pixel needs this many cloud-free looks in BOTH seasons before its peak is
# comparable. Fewer and "not green this year" may just mean "not seen".
MIN_OBSERVATIONS = 3

# ...and a floor is not a balance. A seasonal peak is a MAXIMUM OVER A SAMPLE
# and the expected maximum rises with sample size, so a pixel seen four times
# this year and five times last year has a peak biased DOWN for no reason on
# the ground. Measured over Aleiro: usable pixels averaged 4.76 clear looks
# last season against 3.92 this one.
#
# Requiring n_now >= n_prev per pixel was tried and REJECTED. The imbalance is
# a property of the whole LGA, not of the pixels that fire — flagged pixels sat
# only 0.35 looks below the LGA's own average — so the rule discarded 60% of
# Aleiro and every one of its detections, including ones confirmed against
# imagery. It also fights the ground truth: bright bare soil is routinely
# misread as cloud by Sentinel-2's scene classifier, so a REAL change lowers
# this year's look count as a consequence of having happened.
#
# A uniform, LGA-wide downward shift is what this is, and it is the same shape
# as a weaker rainy season — which produced 1,370 false clusters over Bungudu
# in earlier prototyping. The instrument for it is a shift correction, below,
# not a filter.

# Smallest cluster reported. Below ~1 ha at 30 m (about 11 pixels) speckle and
# field-edge slivers dominate.
MIN_HA = 1.0

# Below this many vegetated pixels an LGA cannot state its own typical season,
# and no shift correction is applied rather than trusting a handful.
MIN_SHIFT_PIXELS = 1000

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


def season_shift(prev: np.ndarray, now: np.ndarray, ok: np.ndarray) -> float:
    """How much LOWER this season's peak runs across the whole LGA.

    Returns a value at or below zero: the median drop in peak greenness over
    ground that was vegetated last season. A weaker rains, or simply fewer
    clear looks this year, moves every pixel down together, and without this
    the detector reads a whole LGA having a poorer year as a whole LGA being
    cleared.

    The median, not the mean, so genuine conversion in part of the LGA cannot
    drag the correction. Only downward shifts are returned: if this season ran
    GREENER, correcting for it would manufacture detections rather than
    prevent them, and the bias must never point that way.
    """
    veg = ok & (prev >= SPARSE_PREV)
    if int(veg.sum()) < MIN_SHIFT_PIXELS:
        return 0.0
    return float(min(np.median(now[veg] - prev[veg]), 0.0))


def corrected(now: np.ndarray, shift: float) -> np.ndarray:
    """This season's peak with the LGA-wide shift taken back out."""
    return now - shift


def stopped_greening(prev: np.ndarray, now: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Was green at last season's peak, is not at this one's — and is not water."""
    return (ok & (prev >= GREEN_PREV) & (now <= BARE_NOW)
            & (now >= WATER_PEAK_MAX))


def became_bare(prev: np.ndarray, now: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Greened at all last season, now effectively non-vegetated (not water)."""
    return (ok & (prev >= SPARSE_PREV) & (now >= WATER_PEAK_MAX)
            & (now <= NONVEG_MAX))


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
