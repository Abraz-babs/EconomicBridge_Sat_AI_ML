"""Tests for the VIIRS Black Marble radiance sampler (sources/viirs_raster.py).

The network/download path is exercised live in staging; here we test the pure,
deterministic pieces: tile selection and nearest-pixel radiance sampling against
a synthetic granule with the same HDF5 layout as a real VNP46A2 file.
"""
from __future__ import annotations

import h5py
import numpy as np

from sources.viirs_raster import (
    FILL_VALUE,
    LAT_DS,
    LON_DS,
    NTL_GAPFILLED,
    sample_granule,
    tile_for,
)


def _make_granule(path, *, n: int = 120) -> tuple[float, float]:
    """Write a synthetic tile h18v07 (lon 0..10, lat 20..10 descending).

    Returns the (lon, lat) of the single bright pixel we plant so the test can
    assert it is recovered.
    """
    lon = np.linspace(0.0, 9.996, n)
    lat = np.linspace(20.0, 10.004, n)   # descending, like the real grid
    ntl = np.zeros((n, n), dtype="float32")
    bright_lon, bright_lat = 7.44, 10.52
    r = int(np.argmin(np.abs(lat - bright_lat)))
    c = int(np.argmin(np.abs(lon - bright_lon)))
    ntl[r, c] = 17.0
    ntl[0, 0] = FILL_VALUE               # a no-data pixel at the NW corner
    with h5py.File(path, "w") as hf:
        hf.create_dataset(NTL_GAPFILLED, data=ntl)
        hf.create_dataset(LAT_DS, data=lat)
        hf.create_dataset(LON_DS, data=lon)
    return bright_lon, bright_lat


def test_tile_for_nigeria():
    assert tile_for(7.44, 10.52) == (18, 7)   # northern (Kaduna belt)
    assert tile_for(7.49, 9.06) == (18, 8)     # FCT / central
    assert tile_for(8.52, 12.00) == (18, 7)    # Kano


def test_sample_granule_recovers_known_pixels(tmp_path):
    p = tmp_path / "vnp46a2.h5"
    blon, blat = _make_granule(p)
    res = sample_granule(p, [(blon, blat), (0.0, 20.0), (50.0, 0.0)])
    by = {(s.lon, s.lat): s for s in res}
    assert by[(blon, blat)].radiance == 17.0       # bright pixel recovered
    assert by[(0.0, 20.0)].radiance is None         # fill → None
    assert by[(50.0, 0.0)].radiance is None          # out of tile → None


def test_sample_granule_dark_pixel_is_zero(tmp_path):
    p = tmp_path / "vnp46a2.h5"
    _make_granule(p)
    # A point away from the planted bright pixel reads ~0 (dark), not None.
    res = sample_granule(p, [(2.0, 15.0)])
    assert res[0].radiance == 0.0
