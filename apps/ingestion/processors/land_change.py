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

# Ground seen as water even ONCE across either season's observations is a river
# channel, a sandbank or a floodplain, and its bars move from year to year. In
# the first measured sample that was the single largest false positive: ten of
# thirteen errors, seven of them the same river through Shinkafi. A road is
# never classified as water on any date, so the cost of this exclusion falls
# almost entirely on the errors.
MAX_WATER_OBSERVATIONS = 0

# Bars and banks sit just OUTSIDE the wetted channel, so the exclusion is grown
# by this many pixels (at 30 m, ~90 m) to cover them.
WATER_BUFFER_PX = 3

# Peak greenness two seasons back for ground to count as having greened then.
# Lower than GREEN_PREV because a third season is corroboration, not the test:
# measured over the labelled points, confirmed conversions sat around 0.48 two
# years back and errors around 0.35.
PRIOR_GREEN = 0.40

KIND_STOPPED = "stopped_greening"
KIND_BARE = "became_bare"


# Greenness at which ground counts as having carried a crop or dense vegetation
# through the rains. Rain-fed farmland here peaks 0.40-0.80; bare and built
# ground stays under 0.15; sparse rangeland sits 0.20-0.35.
#
# NDVI CANNOT TELL A CROP FROM A TREE. What this measures is land that GREENED,
# which is an upper bound on cultivation, never a cropland map. Say "land that
# greened", never "cropland", unless something else establishes cultivation.
GREENED_NDVI = 0.40


@dataclass(frozen=True, slots=True)
class SeasonVegetation:
    """What one LGA's land did in one rainy season.

    This is the agricultural measure, and it is deliberately NOT the change
    detector. The detector asks whether a patch was converted and needs a
    trustworthy baseline in BOTH seasons; where the clouds hid one of them it
    can say nothing, which is why FCT's LGAs reported 0% and looked calm.

    This asks a one-sided question instead — did this pixel reach greenness at
    any point we could see? — so a SINGLE clear look showing green is positive
    evidence. Cloud can only ever make the answer too LOW, so the figure is an
    honest lower bound and every LGA returns one, Abuja included.
    """

    season_year: int
    observed_ha: float      # ground seen clear at least once
    greened_ha: float       # of that, ground that reached GREENED_NDVI
    lga_ha: float           # the whole LGA, for context
    median_peak: float      # typical peak greenness of the greened ground
    median_looks: float     # clear looks the typical observed pixel got
    n_dates: int

    # WHAT KIND of land greened. Greenness alone cannot tell a crop from a
    # tree, and for a farmland platform that is the whole point — so the
    # answer comes from the Esri / Impact Observatory annual land-cover map,
    # not from NDVI. See sources/land_cover.py, including the measured warning
    # that it calls most Sahelian smallholder farming "rangeland".
    greened_on_crops_ha: float = 0.0
    greened_on_rangeland_ha: float = 0.0
    greened_on_trees_ha: float = 0.0
    greened_on_built_ha: float = 0.0
    # Ground the land-cover map calls BARE that is now greening is cultivation
    # EXPANDING, the opposite of the loss this detector chases. Flooded
    # vegetation is fadama — dry-season irrigated farming, significant in Kebbi
    # and wrong to bundle into "not farmland".
    greened_on_bare_ha: float = 0.0
    greened_on_flooded_veg_ha: float = 0.0
    land_cover_year: int | None = None

    @property
    def farmland_ha(self) -> float:
        """Greened ground that could be farmed — crops OR rangeland.

        Reported alongside `greened_on_crops_ha`, never instead of it: crops
        alone is a LOWER bound on farmland here and this sum an UPPER one.
        Never present either as "cropland" on its own.
        """
        return round(self.greened_on_crops_ha + self.greened_on_rangeland_ha, 1)

    @property
    def observed_fraction(self) -> float:
        return self.observed_ha / self.lga_ha if self.lga_ha else 0.0

    @property
    def greened_fraction(self) -> float:
        """Share OF WHAT WAS SEEN, not of the LGA — the only fair denominator
        when cloud hid part of it."""
        return self.greened_ha / self.observed_ha if self.observed_ha else 0.0


@dataclass(frozen=True, slots=True)
class SeasonComparison:
    """Two seasons measured on the SAME ground, so the change means something.

    Each season's `greened_ha` is a lower bound set by how much cloud let us
    see, and the two seasons are never hidden equally. Over FCT's Municipal
    Area Council the raw figures were 43,264 ha last season against 83,395 ha
    this one — which reads as farmland doubling and is very largely the 2025
    rains having been clouded out. Subtracting one lower bound from another
    measures the weather, not the farming.

    So a change is only ever quoted over the footprint BOTH seasons saw.
    """

    common_observed_ha: float
    greened_ha: float           # this season, on the common footprint
    prev_greened_ha: float      # last season, on that same footprint
    looks: float                # clear looks the typical pixel got this season
    prev_looks: float           # ...and last season

    @property
    def comparable(self) -> bool:
        """Is the change worth quoting at all?

        A common footprint fixes "seen versus not seen". It does NOT fix "seen
        twice versus seen eight times": a peak is a MAXIMUM OVER A SAMPLE, so
        the season with fewer clear looks reports a lower peak for no reason on
        the ground, and fewer of its pixels clear the greenness bar.

        FCT's Municipal Area Council shows this exactly — raw +93%, +38.9%
        like-for-like, and its 2025 rains were still barely seen. Both seasons
        must have reached MIN_OBSERVATIONS typically before a change figure
        means anything; where this is False, report the area and say the change
        cannot be established.
        """
        return (self.looks >= MIN_OBSERVATIONS
                and self.prev_looks >= MIN_OBSERVATIONS)

    @property
    def change_ha(self) -> float:
        return round(self.greened_ha - self.prev_greened_ha, 1)

    @property
    def change_fraction(self) -> float:
        if not self.prev_greened_ha:
            return 0.0
        return self.change_ha / self.prev_greened_ha


def like_for_like(peak_now: np.ndarray, seen_now: np.ndarray,
                  peak_prev: np.ndarray, seen_prev: np.ndarray,
                  inside: np.ndarray, *, pixel_ha: float) -> SeasonComparison:
    """Compare two seasons only where both were actually seen."""
    common = (inside & (seen_now >= 1) & (seen_prev >= 1)
              & np.isfinite(peak_now) & np.isfinite(peak_prev))
    return SeasonComparison(
        common_observed_ha=round(float(common.sum()) * pixel_ha, 1),
        greened_ha=round(float((common & (peak_now >= GREENED_NDVI)).sum()) * pixel_ha, 1),
        prev_greened_ha=round(float((common & (peak_prev >= GREENED_NDVI)).sum()) * pixel_ha, 1),
        looks=round(float(np.median(seen_now[common])), 1) if common.any() else 0.0,
        prev_looks=round(float(np.median(seen_prev[common])), 1) if common.any() else 0.0,
    )


def season_vegetation(peak: np.ndarray, seen: np.ndarray, inside: np.ndarray,
                      *, season_year: int, pixel_ha: float, n_dates: int,
                      classes: np.ndarray | None = None,
                      land_cover_year: int | None = None) -> SeasonVegetation:
    """Hectares of an LGA that greened this season, as a lower bound.

    With `classes` from sources/land_cover, the greened ground is also split by
    what KIND of land it is, so trees and built-up can be told apart from
    farmland instead of all counting as "green".
    """
    observed = inside & (seen >= 1) & np.isfinite(peak)
    greened = observed & (peak >= GREENED_NDVI)
    vals = peak[greened]
    by_class: dict[int, float] = {}
    if classes is not None:
        for code in (5, 11, 2, 7, 8, 4):  # crops, rangeland, trees, built, bare, fadama
            by_class[code] = round(
                float((greened & (classes == code)).sum()) * pixel_ha, 1)
    return SeasonVegetation(
        season_year=season_year,
        observed_ha=round(float(observed.sum()) * pixel_ha, 1),
        greened_ha=round(float(greened.sum()) * pixel_ha, 1),
        lga_ha=round(float(inside.sum()) * pixel_ha, 1),
        median_peak=round(float(np.median(vals)), 3) if vals.size else float("nan"),
        median_looks=(round(float(np.median(seen[observed])), 1)
                      if observed.any() else 0.0),
        n_dates=n_dates,
        greened_on_crops_ha=by_class.get(5, 0.0),
        greened_on_rangeland_ha=by_class.get(11, 0.0),
        greened_on_trees_ha=by_class.get(2, 0.0),
        greened_on_built_ha=by_class.get(7, 0.0),
        greened_on_bare_ha=by_class.get(8, 0.0),
        greened_on_flooded_veg_ha=by_class.get(4, 0.0),
        land_cover_year=land_cover_year,
    )


@dataclass(frozen=True, slots=True)
class Hotspot:
    """One contiguous patch of ground that stopped greening."""

    kind: str
    lon: float
    lat: float
    area_ha: float
    peak_prev: float
    peak_now: float
    # Peak greenness TWO seasons back, and whether the ground greened in both
    # prior years. Recorded, never used to filter — see `persistent`.
    peak_prior: float = float("nan")
    # What KIND of land this patch is, from the land-cover map. This is what
    # lets a farmland reader ignore a new road through scrub and keep a
    # building put up on cropland.
    land_cover: str | None = None

    @property
    def persistent(self) -> bool:
        """Did this ground green in BOTH prior seasons?

        A road goes green -> bare once and stays; a sandbar alternates as the
        channel scours and revegetates, and a field alternates with rotation.
        On the labelled points this held for 62% of confirmed conversions and
        only 20% of errors.

        It is REPORTED, not enforced. As a filter it would have halved the
        errors and also discarded three of eight confirmed detections — the
        Zamfara road and the Aleiro construction pad among them. On eighteen
        points that trade is not solid enough to impose on every reader, so the
        evidence is stored and whoever needs the stricter set can ask for it.
        """
        return (self.peak_prior >= PRIOR_GREEN
                and self.peak_prev >= PRIOR_GREEN)


def usable(inside: np.ndarray, prev: np.ndarray, now: np.ndarray,
           n_prev: np.ndarray, n_now: np.ndarray) -> np.ndarray:
    """Pixels inside the LGA that both seasons actually saw often enough."""
    return (inside & np.isfinite(prev) & np.isfinite(now)
            & (n_prev >= MIN_OBSERVATIONS) & (n_now >= MIN_OBSERVATIONS))


def grow(mask: np.ndarray, px: int) -> np.ndarray:
    """Dilate a boolean mask by `px` pixels — numpy only, no scipy in the image."""
    out = mask.copy()
    for _ in range(px):
        g = out.copy()
        g[1:, :] |= out[:-1, :]
        g[:-1, :] |= out[1:, :]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def dry_land(n_water: np.ndarray, now_raw: np.ndarray) -> np.ndarray:
    """Ground that is not river, sandbank, floodplain or pond.

    Two tests, because they catch different things. The observation count
    catches a channel that held water on any date we looked. The raw peak
    catches standing water on ground the classifier missed: land reads above
    zero at its seasonal peak, and this must use the RAW peak, not the
    season-corrected one — a shift correction could otherwise lift genuinely
    negative water back over the line, which is exactly how two ponds reached
    the first measured sample.
    """
    wet = (n_water > MAX_WATER_OBSERVATIONS) | (now_raw < WATER_PEAK_MAX)
    return ~grow(wet, WATER_BUFFER_PX)


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


def _dominant_class(classes: np.ndarray, sub: np.ndarray) -> str | None:
    """The land-cover class most of this patch sits on."""
    from sources.land_cover import NAMES

    vals = classes[sub & np.isfinite(classes)]
    if not vals.size:
        return None
    codes, counts = np.unique(vals.astype(int), return_counts=True)
    return NAMES.get(int(codes[counts.argmax()]))


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
    prior: np.ndarray | None = None,
    classes: np.ndarray | None = None,
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
            peak_prior=(round(_median_in(prior[r0:r1, c0:c1], sub), 3)
                        if prior is not None else float("nan")),
            land_cover=(_dominant_class(classes[r0:r1, c0:c1], sub)
                        if classes is not None else None),
        ))
    return sorted(out, key=lambda h: h.area_ha, reverse=True)
