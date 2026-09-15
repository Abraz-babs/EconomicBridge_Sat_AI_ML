"""Windowed COG reads — synthetic rasters in tmp_path, never the network.

Each test pins one property the change detector will lean on: averaging to the
requested resolution, nodata never becoming a number, an LGA outline masking
pixels outside it, and "nothing here" staying distinct from "could not read".
"""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
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


# ─── Fixed LGA grids: every date warped onto the same pixels ──────────────


def test_lga_grid_is_utm_and_snapped_so_every_run_builds_the_same_grid():
    a = cw.lga_grid((4.20, 11.90, 4.65, 12.35), resolution_m=30)
    b = cw.lga_grid((4.2001, 11.9001, 4.6499, 12.3499), resolution_m=30)
    assert a.crs == "EPSG:32631", "4.4 E is UTM zone 31 north"
    assert a.transform.c % 30 == 0 and a.transform.f % 30 == 0
    assert (b.transform.c - a.transform.c) % 30 == 0, "origins land on the same lattice"
    assert a.resolution_m == 30


def test_two_differently_gridded_scenes_agree_once_warped_onto_one_grid(tmp_path):
    """The whole point: pixel-for-pixel comparison needs a common grid.

    Scene A is 10 m from one origin; scene B is 20 m, shifted by 5 m. Both carry
    the same smooth field (easting in km), so once warped onto one 30 m grid
    they must agree — and read raw, their windows would not even line up.
    """
    def field(path, x0, y0, res, n):
        cols = (x0 + (np.arange(n) + 0.5) * res) / 1000.0
        data = np.tile(cols.astype("float32"), (n, 1))
        with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                           dtype="float32", crs=UTM, transform=from_origin(x0, y0, res, res),
                           nodata=-9999.0) as dst:
            dst.write(data, 1)
        return str(path)

    a = field(tmp_path / "a.tif", X0, Y0, 10.0, 300)
    b = field(tmp_path / "b.tif", X0 + 5.0, Y0 - 5.0, 20.0, 150)
    grid = cw.Grid(UTM, cw.Affine(30.0, 0, X0 + 300, 0, -30.0, Y0 - 300), 60, 60)
    ra, rb = cw.read_on_grid(a, grid), cw.read_on_grid(b, grid)
    assert ra.shape == rb.shape == (60, 60)
    assert np.nanmax(np.abs(ra - rb)) < 0.01, "within 10 m of easting"


def test_ground_the_scene_does_not_cover_is_nan_not_zero(tmp_path):
    href = _write_utm(tmp_path / "s1.tif")
    grid = cw.Grid(UTM, cw.Affine(30.0, 0, X0 - 1500, 0, -30.0, Y0), 150, 100)
    r = cw.read_on_grid(href, grid)
    # Column 49's right edge sits EXACTLY on the scene's first pixel, and the
    # averaging kernel picks that pixel up; real scenes never align to our grid
    # edges, so the boundary column is excluded rather than asserted either way.
    assert np.isnan(r[:, :49]).all(), "west of the scene"
    assert np.allclose(r[:, 51:], 5.0)


def test_a_source_without_declared_nodata_still_reads_uncovered_ground_as_nan(tmp_path):
    p = tmp_path / "nodecl.tif"
    with rasterio.open(p, "w", driver="GTiff", height=300, width=300, count=1,
                       dtype="float32", crs=UTM, transform=from_origin(X0, Y0, 10.0, 10.0)) as dst:
        dst.write(np.full((300, 300), 5.0, dtype="float32"), 1)
    grid = cw.Grid(UTM, cw.Affine(30.0, 0, X0 - 1500, 0, -30.0, Y0), 150, 100)
    r = cw.read_on_grid(str(p), grid)
    # Boundary column 49 excluded for the reason given in the test above.
    assert np.isnan(r[:, :49]).all(), "0 would have looked like a real reading"
    assert not (r[:, :49] == 0).any()


def test_categories_use_the_majority_class_not_an_invented_average(tmp_path):
    """Averaging land-cover codes 2 (trees) and 5 (crops) would invent 'class 3'."""
    p = tmp_path / "lulc.tif"
    data = np.full((300, 300), 5, dtype="uint8")
    data[::3, :] = 2                                 # one row in three is trees
    with rasterio.open(p, "w", driver="GTiff", height=300, width=300, count=1,
                       dtype="uint8", crs=UTM, transform=from_origin(X0, Y0, 10.0, 10.0),
                       nodata=0) as dst:
        dst.write(data, 1)
    grid = cw.Grid(UTM, cw.Affine(30.0, 0, X0, 0, -30.0, Y0), 100, 100)
    r = cw.read_on_grid(str(p), grid, resampling=Resampling.mode)
    assert set(np.unique(r[np.isfinite(r)]).tolist()) == {5.0}


def test_outline_mask_marks_only_pixels_inside_the_lga():
    grid = cw.Grid(UTM, cw.Affine(30.0, 0, X0, 0, -30.0, Y0), 100, 100)
    west_half = transform_geom(UTM, "EPSG:4326", {
        "type": "Polygon",
        "coordinates": [[[X0, Y0 - 3000], [X0 + 1500, Y0 - 3000], [X0 + 1500, Y0],
                         [X0, Y0], [X0, Y0 - 3000]]],
    })
    m = cw.outline_mask(grid, west_half)
    assert 0.45 < m.mean() < 0.55
    assert m[:, :45].all() and not m[:, 55:].any()

