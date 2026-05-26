"""Tests for sources.cog_sampler — generic COG point reader (Slice 09).

The fixture builds a tiny GeoTIFF on disk per-test so we never depend
on network or external rasters in CI. Each test exercises one corner
of the sampler contract:

  * value at a known pixel
  * nodata pixel → value=None, valid=False
  * point outside raster extent → valid=False
  * empty points list → empty result
  * reprojection (raster in EPSG:3857, points passed as 4326)
  * invalid URL → CogSamplerError
"""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from sources.cog_sampler import CogSamplerError, sample_points


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _write_tiny_geotiff(
    path,
    *,
    bbox=(-1.0, -1.0, 1.0, 1.0),   # lon_min, lat_min, lon_max, lat_max
    shape=(10, 10),                # rows, cols
    crs="EPSG:4326",
    nodata=-9999.0,
    fill: float = 100.0,
):
    """Write a deterministic GeoTIFF: every pixel = its column index * 10
    + fill. Centre pixel of the (10, 10) grid is 40 + fill."""
    rows, cols = shape
    transform = from_bounds(*bbox, cols, rows)
    data = (
        np.tile(np.arange(cols, dtype="float32"), (rows, 1)) * 10.0 + fill
    )
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=rows, width=cols,
        count=1, dtype="float32",
        crs=crs, transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def tiny_cog(tmp_path):
    p = tmp_path / "tiny.tif"
    _write_tiny_geotiff(p)
    return str(p)


# ─── Behaviour ────────────────────────────────────────────────────────────


def test_sample_points_returns_pixel_value_at_known_location(tiny_cog):
    # Bbox -1..1, 10 cols → each cell is 0.2°. Col 5 (centred at lon ~0.1)
    # → value = 5 * 10 + 100 = 150.
    samples = sample_points(tiny_cog, [(0.1, 0.0)])
    assert len(samples) == 1
    s = samples[0]
    assert s.valid is True
    assert s.value == pytest.approx(150.0)
    assert s.band == 1


def test_sample_points_multiple_returns_one_per_input(tiny_cog):
    samples = sample_points(tiny_cog, [
        (-0.9, 0.0),   # col 0 → 100
        (0.5, 0.0),    # col 7 → 170
        (0.9, 0.0),    # col 9 → 190
    ])
    assert [s.value for s in samples] == pytest.approx([100.0, 170.0, 190.0])
    assert all(s.valid for s in samples)


def test_sample_points_nodata_pixel_returns_invalid(tmp_path):
    p = tmp_path / "nodata.tif"
    rows, cols = 4, 4
    data = np.full((rows, cols), -9999.0, dtype="float32")
    data[2, 2] = 42.0  # one valid pixel
    transform = from_bounds(0.0, 0.0, 4.0, 4.0, cols, rows)
    with rasterio.open(
        p, "w", driver="GTiff", height=rows, width=cols,
        count=1, dtype="float32", crs="EPSG:4326",
        transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)

    # (0.5, 0.5) hits a nodata pixel, (2.5, 1.5) hits the valid 42.
    samples = sample_points(str(p), [(0.5, 0.5), (2.5, 1.5)])
    assert samples[0].valid is False
    assert samples[0].value is None
    assert samples[1].valid is True
    assert samples[1].value == pytest.approx(42.0)


def test_sample_points_outside_extent_returns_invalid(tiny_cog):
    samples = sample_points(tiny_cog, [(50.0, 50.0)])
    assert samples[0].valid is False
    assert samples[0].value is None


def test_sample_points_empty_input_returns_empty(tiny_cog):
    assert sample_points(tiny_cog, []) == []


def test_sample_points_reprojects_when_raster_crs_differs(tmp_path):
    """Raster is in EPSG:3857 (Web Mercator). Points are in EPSG:4326
    and must be reprojected before sampling — otherwise (0, 0) lat/lon
    would miss the pixel grid entirely."""
    p = tmp_path / "mercator.tif"
    # 4326 bbox roughly -1..1 → 3857 bbox approx ±111320 m.
    _write_tiny_geotiff(p, bbox=(-111320.0, -111320.0, 111320.0, 111320.0),
                        crs="EPSG:3857")
    samples = sample_points(p, [(0.0, 0.0)])
    # Centre of grid in 3857 → centre col (col 5 since shape=10) → value 150.
    assert samples[0].valid is True
    assert samples[0].value == pytest.approx(150.0)


def test_invalid_url_raises_cog_sampler_error():
    with pytest.raises(CogSamplerError):
        sample_points("/no/such/file.tif", [(0.0, 0.0)])


def test_sample_points_negative_pixel_treated_as_nodata_when_sentinel(tmp_path):
    """WorldPop uses -99999 as nodata even though it's a 'valid' float.
    The sampler treats values <= -9999 as nodata even when the COG's
    declared nodata is something else (or absent)."""
    p = tmp_path / "ww_sentinel.tif"
    rows, cols = 3, 3
    data = np.array([[-99999, 5, 10],
                     [15, 20, 25],
                     [30, 35, 40]], dtype="float32")
    transform = from_bounds(0.0, 0.0, 3.0, 3.0, cols, rows)
    with rasterio.open(
        p, "w", driver="GTiff", height=rows, width=cols,
        count=1, dtype="float32", crs="EPSG:4326",
        transform=transform, nodata=None,
    ) as dst:
        dst.write(data, 1)
    samples = sample_points(str(p), [(0.5, 2.5), (1.5, 1.5)])
    assert samples[0].valid is False  # -99999 sentinel
    assert samples[1].valid is True
    assert samples[1].value == pytest.approx(20.0)
