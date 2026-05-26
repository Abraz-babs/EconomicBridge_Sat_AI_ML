"""Generic Cloud-Optimized GeoTIFF (COG) point sampler.

This is the Phase B foundation that turns the catalog/metadata clients
shipped in Slice 01.live into real per-pixel reads. Given a COG URL
(HTTPS or s3://) and a list of `(lon, lat)` points in EPSG:4326, we
return the raster value at each pixel — without downloading the whole
file.

Why a COG matters
-----------------
A Cloud-Optimized GeoTIFF stores its internal tiles + overview pyramid
contiguously and exposes its layout via a tiny header. With rasterio's
`/vsicurl/` (HTTPS) or `/vsis3/` (S3) drivers, opening a COG fires a
single ranged-HTTP request for the header, then one more ranged read
per pixel cluster. A 200 MB WorldPop tile yields ~50 KB of network
traffic for a few hundred point reads.

What this *isn't*
-----------------
* Not a windowed read or polygon extractor — extend with `dataset.read`
  over a `Window` if/when a slice needs that.
* Not a CRS reprojector — caller passes lon/lat in EPSG:4326 and we
  reproject on the fly only if the COG declares a different CRS.
* Not async by itself — rasterio is sync C bindings, so callers should
  wrap `sample_points` with `asyncio.to_thread` (the WorldPop ingest
  task does this).
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator

import rasterio
from rasterio.env import Env
from rasterio.warp import transform as rio_transform

log = logging.getLogger(__name__)


# On Windows dev boxes that also run PostgreSQL/PostGIS, the PostGIS-bundled
# PROJ database lands on PATH and confuses rasterio's newer PROJ build with
# "DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is expected". Pin
# PROJ_DATA at rasterio's own bundled DB so import order doesn't matter.
_RASTERIO_PROJ = os.path.join(os.path.dirname(rasterio.__file__), "proj_data")
if os.path.isdir(_RASTERIO_PROJ):
    os.environ.setdefault("PROJ_DATA", _RASTERIO_PROJ)
    # Older GDAL/PROJ still honour PROJ_LIB even though it's deprecated.
    os.environ.setdefault("PROJ_LIB", _RASTERIO_PROJ)


# rasterio/GDAL env tuned for ranged COG reads. Disabling directory listing
# on cloud URLs avoids accidental HEAD requests that many object stores
# reject (S3 anonymous reads etc.). rasterio 1.5+ wants typed values
# (int/bool) rather than the historical all-string convention.
_GDAL_ENV: dict[str, object] = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_USE_HEAD": False,
    "GDAL_HTTP_MULTIPLEX": True,
    "GDAL_HTTP_VERSION": "2",
    "GDAL_HTTP_TIMEOUT": 30,
    "GDAL_CACHEMAX": 67_108_864,   # 64 MB
    "VSI_CACHE": True,
    "VSI_CACHE_SIZE": 16_777_216,  # 16 MB
}


@dataclass(frozen=True, slots=True)
class CogSample:
    """One pixel value sampled from a COG at a known (lon, lat)."""

    lon: float
    lat: float
    value: float | None       # None when the pixel is nodata / off-raster
    valid: bool               # False mirrors value=None — convenience for joins
    band: int                 # 1-indexed COG band that was read


class CogSamplerError(RuntimeError):
    """Could not open the COG, or all reads failed."""


def _to_vsicurl(url: object) -> str:
    """Normalise an HTTPS or s3:// URL to a GDAL VSI prefix.

    Accepts str or pathlib.Path; the latter is normalised via `os.fspath`
    so test callers can pass a `tmp_path / "foo.tif"` directly.
    rasterio understands `https://...` directly *if* curl is built in,
    but explicitly using `/vsicurl/` is more portable across GDAL builds
    and stays inside the documented contract.
    """
    s = os.fspath(url) if hasattr(url, "__fspath__") else str(url)
    if s.startswith("/vsi"):
        return s
    if s.startswith("s3://"):
        return "/vsis3/" + s[len("s3://"):]
    if s.startswith(("http://", "https://")):
        return "/vsicurl/" + s
    # Plain local path — rasterio opens it as-is.
    return s


@contextmanager
def _open_cog(url: str) -> Iterator[rasterio.io.DatasetReader]:
    """Open a COG with the tuned GDAL env. Yields the rasterio dataset."""
    with Env(**_GDAL_ENV):
        try:
            ds = rasterio.open(_to_vsicurl(url))
        except (rasterio.errors.RasterioIOError, OSError) as e:
            raise CogSamplerError(f"Could not open COG at {url}: {e}") from e
        try:
            yield ds
        finally:
            ds.close()


def sample_points(
    url: str,
    points: Iterable[tuple[float, float]],
    *,
    band: int = 1,
) -> list[CogSample]:
    """Sample one or more (lon, lat) points from a COG and return the values.

    Points are in EPSG:4326. If the COG declares a different CRS, the
    points are reprojected on the fly. Pixels that fall on nodata or
    outside the raster's extent come back with `value=None, valid=False`
    — never coerced to 0.

    Raises CogSamplerError when the COG can't be opened at all.
    """
    pts = list(points)
    if not pts:
        return []

    with _open_cog(url) as ds:
        if ds.count < band:
            raise CogSamplerError(
                f"COG at {url} has {ds.count} band(s); band {band} requested"
            )

        # Reproject lon/lat → raster CRS if needed.
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        if ds.crs and ds.crs.to_epsg() != 4326:
            xs, ys = rio_transform("EPSG:4326", ds.crs, lons, lats)
        else:
            xs, ys = lons, lats

        # rasterio.sample expects an iterable of (x, y) in the dataset CRS.
        # It returns one ndarray per point (length = band count). We pull
        # only the requested band.
        raw_iter = ds.sample(zip(xs, ys), indexes=[band])
        nodata = ds.nodatavals[band - 1] if ds.nodatavals else None
        out: list[CogSample] = []
        for (lon, lat), raw in zip(pts, raw_iter):
            try:
                pixel = float(raw[0])
            except (IndexError, TypeError, ValueError):
                out.append(CogSample(lon=lon, lat=lat, value=None,
                                     valid=False, band=band))
                continue

            # Two paths to nodata: the COG's declared nodata, and the
            # WorldPop-ish -99999 sentinel (which raster producers sometimes
            # bake into the pixels without declaring a nodata band).
            declared_nodata = (
                nodata is not None and pixel == nodata
            )
            sentinel_nodata = pixel <= -9999
            is_nodata = declared_nodata or sentinel_nodata
            if is_nodata:
                out.append(CogSample(lon=lon, lat=lat, value=None,
                                     valid=False, band=band))
            else:
                out.append(CogSample(lon=lon, lat=lat, value=pixel,
                                     valid=True, band=band))
        return out
