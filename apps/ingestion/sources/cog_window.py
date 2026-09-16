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
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import from_bounds

from config import get_settings
from sources.cog_sampler import open_cog

# Rasters sometimes bake this sentinel in without declaring nodata; the same
# rule as cog_sampler, so the two readers agree on what "no data" is. Sentinel-1
# RTC declares -32768, which this also covers.
SENTINEL_NODATA = -9999.0

# Destination nodata for warps from sources that declare none (below the
# sentinel, so it is always masked). Only valid for signed and floating
# rasters — see _fill_for.
_WARP_NODATA = -32768.0


def _fill_for(dtype: str) -> float:
    """A nodata value the source dtype can actually hold.

    GDAL refuses a warp whose nodata falls outside the band's range, so an
    8-bit raster given -32768 fails the read outright — found on Sentinel-2's
    uint8 `visual` asset. Unsigned bands use 0, which is what those products
    declare as empty anyway; everything else keeps the sentinel.
    """
    return 0.0 if np.dtype(dtype).kind == "u" else _WARP_NODATA

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


@dataclass(frozen=True)
class Grid:
    """A fixed pixel grid. Every scene of one LGA is warped onto this, so a
    given pixel is the same patch of ground on every date."""

    crs: str
    transform: Affine
    width: int
    height: int

    @property
    def resolution_m(self) -> float:
        """Pixel size in metres (UTM grids are square)."""
        return abs(self.transform.a)


def lga_grid(bbox: tuple[float, float, float, float],
             resolution_m: float | None = None) -> Grid:
    """A UTM grid covering a lon/lat `bbox`, snapped to whole pixels.

    The zone comes from the bbox centre. Snapping the origin to multiples of the
    resolution means every run builds the identical grid for the same LGA, so
    results stored on different days line up pixel for pixel.
    """
    res = float(resolution_m or get_settings().open_archive_resolution_m)
    lon_c, lat_c = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    zone = int((lon_c + 180) // 6) + 1
    crs = f"EPSG:{(32600 if lat_c >= 0 else 32700) + zone}"
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
    left, bottom = math.floor(left / res) * res, math.floor(bottom / res) * res
    right, top = math.ceil(right / res) * res, math.ceil(top / res) * res
    return Grid(crs, Affine(res, 0.0, left, 0.0, -res, top),
                int(round((right - left) / res)), int(round((top - bottom) / res)))


def outline_mask(grid: Grid, geometry: dict) -> np.ndarray:
    """True where a grid pixel's centre falls inside a lon/lat outline."""
    outline = transform_geom("EPSG:4326", grid.crs, geometry)
    return rasterize([(outline, 1)], out_shape=(grid.height, grid.width),
                     transform=grid.transform, fill=0, dtype="uint8").astype(bool)


def read_on_grid(href: str, grid: Grid, *, band: int = 1,
                 resampling: Resampling = Resampling.average) -> np.ndarray:
    """Warp a COG onto `grid` and return float32 with NaN for nodata.

    Scenes from different dates arrive on slightly different native grids, and
    the frames of one pass can sit in different UTM zones. A pixel-by-pixel
    comparison only means anything after each is warped onto the SAME grid —
    found while prototyping on 2026-09-15, before any detector was written.

    Use Resampling.average for measurements (radar power, reflectance) and
    Resampling.mode for categories (land-cover classes): averaging class codes
    invents classes that do not exist. Pixels the scene does not cover are NaN.
    """
    with open_cog(href) as ds:
        # A source without declared nodata would otherwise fill uncovered
        # pixels with 0 — a valid-looking value. Give the warp one to use.
        dst_nodata = ds.nodata if ds.nodata is not None else _fill_for(ds.dtypes[band - 1])
        with WarpedVRT(ds, crs=grid.crs, transform=grid.transform,
                       width=grid.width, height=grid.height, resampling=resampling,
                       src_nodata=ds.nodata, nodata=dst_nodata) as vrt:
            a = vrt.read(band, masked=True).astype("float32").filled(np.nan)
    a[~np.isfinite(a) | (a <= SENTINEL_NODATA)] = np.nan
    return a


def to_db(linear: np.ndarray) -> np.ndarray:
    """Linear radar power -> decibels, floored so a zero cannot become -inf."""
    return (10.0 * np.log10(np.maximum(linear, 1e-6))).astype("float32")
