"""Windowed COG reads — synthetic rasters in tmp_path, never the network.

Each test pins one property the change detector will lean on: averaging to the
requested resolution, nodata never becoming a number, an LGA outline masking
pixels outside it, and "nothing here" staying distinct from "could not read".
"""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds, transform_geom

from sources import cog_window as cw


# ─── Windowed reads (synthetic rasters, no network) ───────────────────────

UTM = "EPSG:32631"
X0, Y0 = 500_000.0, 1_340_010.0      # upper-left corner, ~12.1 N 3 E


def _write_utm(path, *, size=300, res=10.0, fill=5.0, nodata=-9999.0, hole=None):
    data = np.full((size, size), fill, dtype="float32")
    if hole:
        r0, r1, c0, c1 = hole
        data[r0:r1, c0:c1] = nodata
    with rasterio.open(path, "w", driver="GTiff", height=size, width=size, count=1,
                       dtype="float32", crs=UTM, transform=from_origin(X0, Y0, res, res),
                       nodata=nodata) as dst:
        dst.write(data, 1)
    return str(path)


def _utm_box_lonlat(x0, y0, x1, y1):
    return transform_bounds(UTM, "EPSG:4326", x0, y0, x1, y1)


def test_a_whole_window_is_averaged_down_to_the_requested_resolution(tmp_path):
    href = _write_utm(tmp_path / "s1.tif")
    r = cw.read_window(href, _utm_box_lonlat(X0, Y0 - 3000, X0 + 3000, Y0), resolution_m=30)
    assert r.values.shape == (100, 100), "10 m -> 30 m is a 3x3 average"
    assert np.allclose(r.values, 5.0)
    assert r.valid_fraction == 1.0
    assert r.resolution_m == pytest.approx(30.0, rel=0.02)


def test_nodata_becomes_nan_and_counts_against_coverage(tmp_path):
    href = _write_utm(tmp_path / "s1.tif", hole=(0, 30, 0, 30))    # aligned to 3x3 blocks
    r = cw.read_window(href, _utm_box_lonlat(X0, Y0 - 3000, X0 + 3000, Y0), resolution_m=30)
    assert np.isnan(r.values[:10, :10]).all()
    assert r.valid_fraction == pytest.approx(0.99, abs=1e-6)


def test_an_lga_outline_masks_pixels_outside_it(tmp_path):
    href = _write_utm(tmp_path / "s1.tif")
    west_half = transform_geom(UTM, "EPSG:4326", {
        "type": "Polygon",
        "coordinates": [[[X0, Y0 - 3000], [X0 + 1500, Y0 - 3000], [X0 + 1500, Y0],
                         [X0, Y0], [X0, Y0 - 3000]]],
    })
    r = cw.read_window(href, _utm_box_lonlat(X0, Y0 - 3000, X0 + 3000, Y0),
                       resolution_m=30, geometry=west_half)
    share_inside = r.inside.mean()
    assert 0.45 < share_inside < 0.55
    assert r.valid.sum() == r.inside.sum(), "every inside pixel carries data here"


def test_a_window_that_misses_the_raster_is_empty_not_an_exception(tmp_path):
    href = _write_utm(tmp_path / "s1.tif")
    r = cw.read_window(href, (10.0, 5.0, 10.1, 5.1), resolution_m=30)
    assert r.values.size == 0
    assert r.valid_fraction == 0.0


def test_finer_than_native_is_never_invented(tmp_path):
    href = _write_utm(tmp_path / "s1.tif")
    r = cw.read_window(href, _utm_box_lonlat(X0, Y0 - 3000, X0 + 3000, Y0), resolution_m=5)
    assert r.values.shape == (300, 300)


def test_geographic_rasters_are_resampled_in_metres_not_degrees(tmp_path):
    """0.0003 deg is ~33 m. Treating degrees as metres would collapse it to 1 px."""
    p = tmp_path / "geo.tif"
    with rasterio.open(p, "w", driver="GTiff", height=90, width=90, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(4.0, 12.027, 0.0003, 0.0003), nodata=-9999.0) as dst:
        dst.write(np.ones((90, 90), dtype="float32"), 1)
    r = cw.read_window(str(p), (4.0, 12.0, 4.027, 12.027), resolution_m=100)
    assert 26 <= r.values.shape[0] <= 34 and 26 <= r.values.shape[1] <= 34


def test_to_db_floors_zero_instead_of_minus_infinity():
    out = cw.to_db(np.array([1.0, 0.1, 0.0], dtype="float32"))
    assert out.tolist() == pytest.approx([0.0, -10.0, -60.0])
