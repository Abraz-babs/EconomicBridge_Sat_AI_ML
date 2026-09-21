"""Land cover classes per pixel — what KIND of land this is.

WHY
---
Greenness alone cannot tell a crop from a tree, and for a farmland platform
that distinction is the whole point: a tree-covered hill greening every year is
not farmland, and a new building on cropland is not "land that stopped
greening". The Esri / Impact Observatory annual product answers exactly that
question and sits in the same archive we already read, so there is no reason to
work without it.

`io-lulc-annual-v02` — 10 m, ANNUAL to 2024 (fresher than ESA WorldCover's 2021
snapshot), 9 classes, derived from Sentinel-2.

KNOWN LIMIT, MEASURED — READ BEFORE USING `CROPS` ALONE
-------------------------------------------------------
It under-maps West African smallholder rain-fed farming. Over Aleiro (Kebbi) it
calls 85.2% of the LGA RANGELAND and only 8.4% CROPS, while our own measurement
shows 96% of that same ground reaching full greenness in the rains. Sahelian
bush-fallow farming does not look like the irrigated blocks these models were
mostly trained on.

So `CROPS` is a LOWER bound on farmland and `CROPS + RANGELAND` an upper one,
and both are reported rather than either being passed off as "cropland". What
the classes reliably do separate is the part that matters most here: TREES,
BUILT and WATER are genuinely not farmland, and excluding them is sound.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
from rasterio.enums import Resampling

from sources import cog_window as cw
from sources import open_archive as oa

log = logging.getLogger(__name__)

COLLECTION = "io-lulc-annual-v02"

WATER = 1
TREES = 2
FLOODED_VEG = 4
CROPS = 5
BUILT = 7
BARE = 8
SNOW = 9
CLOUDS = 10
RANGELAND = 11

NAMES = {WATER: "water", TREES: "trees", FLOODED_VEG: "flooded_vegetation",
         CROPS: "crops", BUILT: "built", BARE: "bare", SNOW: "snow",
         CLOUDS: "clouds", RANGELAND: "rangeland"}

# Land that can carry a crop. Rangeland is included because this product calls
# most Sahelian farmland rangeland — see the module docstring; the two are
# reported separately so a reader is never handed the sum as "cropland".
FARMABLE = (CROPS, RANGELAND)

# Land that is definitively NOT farmland, whatever it does in NDVI.
NOT_FARMLAND = (WATER, TREES, BUILT, SNOW)

# The map is annual. Anything in this window describes the land as it is now
# well enough to say what KIND it is; we are not dating a change from it.
_SEARCH_FROM = datetime(2022, 1, 1, tzinfo=timezone.utc)
_SEARCH_TO = datetime(2026, 12, 31, tzinfo=timezone.utc)


async def classes_on_grid(bbox, grid) -> tuple[np.ndarray | None, int | None]:
    """Land-cover class per pixel of `grid`, and the year it describes.

    Returns (None, None) when the archive has no cover — the caller must then
    report land WITHOUT a breakdown rather than guessing at one.
    """
    scenes = await oa.search(COLLECTION, bbox, _SEARCH_FROM, _SEARCH_TO)
    if not scenes:
        log.warning("land_cover: no %s item covering %s", COLLECTION, bbox)
        return None, None
    scene = max(scenes, key=lambda s: s.datetime)
    asset = "data" if "data" in scene.assets else sorted(scene.assets)[0]
    href = await oa.signed_href(COLLECTION, scene.assets[asset])
    # Resampling.mode, never average: averaging class codes invents classes
    # that do not exist. rasterio is synchronous, so the read goes to a thread
    # rather than blocking the loop the archive reads are sharing.
    arr = await asyncio.to_thread(cw.read_on_grid, href, grid,
                                  resampling=Resampling.mode)
    return arr, scene.datetime.year


def breakdown(classes: np.ndarray, mask: np.ndarray, *,
              pixel_ha: float) -> dict[str, float]:
    """Hectares per land-cover class within `mask`."""
    out: dict[str, float] = {}
    vals = classes[mask & np.isfinite(classes)]
    if not vals.size:
        return out
    for code, count in zip(*np.unique(vals.astype(int), return_counts=True)):
        out[NAMES.get(int(code), f"class_{int(code)}")] = round(
            float(count) * pixel_ha, 1)
    return out


def is_farmable(classes: np.ndarray) -> np.ndarray:
    """Ground that could carry a crop — crops OR rangeland. See FARMABLE."""
    return np.isin(classes, FARMABLE)


def is_not_farmland(classes: np.ndarray) -> np.ndarray:
    """Water, trees, built and snow. Never farmland, whatever NDVI says."""
    return np.isin(classes, NOT_FARMLAND)
