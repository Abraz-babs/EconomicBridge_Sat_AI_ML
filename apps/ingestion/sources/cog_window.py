"""Windowed COG reads — a whole area at a chosen resolution, not a point.

sources/cog_sampler.py reads single pixels at points. Change detection needs
the opposite: every pixel across an LGA, on a regular grid, with an outline
mask saying which of them belong to that LGA. This is that reader. It reuses
cog_sampler's opener, so the tuned GDAL environment and the Windows PROJ pin
live in one place.

Kept out of sources/open_archive.py on purpose: nothing here knows about STAC,
signing or tenants, so it works on any COG — Sentinel from the open archive,
WorldPop, or a synthetic raster in a test.

rasterio is synchronous: callers run read_window via asyncio.to_thread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import from_bounds

from config import get_settings
from sources.cog_sampler import open_cog

# Rasters sometimes bake this sentinel in without declaring nodata; the same
# rule as cog_sampler, so the two readers agree on what "no data" is. Sentinel-1
# RTC declares -32768, which this also covers.
SENTINEL_NODATA = -9999.0

# Metres per degree, for rasters stored in geographic coordinates.
_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON_EQ = 111_320.0


@dataclass(frozen=True)
class WindowRead:
    """Pixels from one COG window, on a regular grid in the raster's own CRS."""

    values: np.ndarray        # float32; NaN where nodata or off the raster
    inside: np.ndarray        # bool; pixel centre inside the requested outline
    transform: Affine
    crs: str
    resolution_m: float

    @property
    def valid(self) -> np.ndarray:
        """Pixels that both carry data and fall inside the outline."""
        return self.inside & ~np.isnan(self.values)

    @property
    def valid_fraction(self) -> float:
        """Share of the outline actually observed. 0.0 when nothing is inside."""
        n = int(self.inside.sum())
        return float(self.valid.sum()) / n if n else 0.0


def _native_m(ds, bbox: tuple[float, float, float, float]) -> float:
    """Native pixel size in metres, whatever units the raster is stored in."""
    rx, ry = abs(ds.res[0]), abs(ds.res[1])
    if ds.crs is not None and ds.crs.is_geographic:
        lat = math.radians((bbox[1] + bbox[3]) / 2)
        return (rx * _M_PER_DEG_LON_EQ * math.cos(lat) + ry * _M_PER_DEG_LAT) / 2
    return (rx + ry) / 2


def read_window(
    href: str,
    bbox: tuple[float, float, float, float],
    *,
    resolution_m: float | None = None,
    geometry: dict | None = None,
    band: int = 1,
) -> WindowRead:
    """Read the part of a COG covering `bbox` (lon/lat), averaged to `resolution_m`.

    Never upsamples: asking for finer than native returns native pixels. Values
    come back in the asset's own units — check them per collection before
    comparing (Sentinel-1 RTC is linear; see sources/open_archive). If
    `geometry` (a lon/lat GeoJSON outline) is given, pixels whose centre falls
    outside it are marked inside=False. A bbox that misses the raster returns an
    empty read with valid_fraction 0.0, never an exception — "nothing here" and
    "could not read" are different, and only the second should raise.
    """
    res = float(resolution_m or get_settings().open_archive_resolution_m)
    with open_cog(href) as ds:
        left, bottom, right, top = transform_bounds("EPSG:4326", ds.crs, *bbox, densify_pts=21)
        b = ds.bounds
        left, bottom = max(left, b.left), max(bottom, b.bottom)
        right, top = min(right, b.right), min(top, b.top)
        crs = ds.crs.to_string()
        if left >= right or bottom >= top:
            empty = np.zeros((0, 0), dtype="float32")
            return WindowRead(empty, empty.astype(bool), ds.transform, crs, res)

        win = from_bounds(left, bottom, right, top, transform=ds.transform)
        native = _native_m(ds, bbox)
        factor = max(1.0, res / native)
        h = max(1, int(round(win.height / factor)))
        w = max(1, int(round(win.width / factor)))
        arr = ds.read(band, window=win, out_shape=(h, w),
                      resampling=Resampling.average, masked=True)
        values = arr.astype("float32").filled(np.nan)
        values[~np.isfinite(values) | (values <= SENTINEL_NODATA)] = np.nan
        out_transform = ds.window_transform(win) * Affine.scale(win.width / w, win.height / h)

        inside = np.ones((h, w), dtype=bool)
        if geometry is not None:
            outline = transform_geom("EPSG:4326", ds.crs, geometry)
            inside = rasterize([(outline, 1)], out_shape=(h, w), transform=out_transform,
                               fill=0, dtype="uint8").astype(bool)
        return WindowRead(values, inside, out_transform, crs, native * (win.width / w))


def to_db(linear: np.ndarray) -> np.ndarray:
    """Linear radar power -> decibels, floored so a zero cannot become -inf."""
    return (10.0 * np.log10(np.maximum(linear, 1e-6))).astype("float32")
