"""Night-light trend (Mobility Compass) — the pure rules in tasks/night_light_trend.py."""
from __future__ import annotations

import numpy as np

from tasks.night_light_trend import (
    LIT_NW,
    lga_sums,
    pixel_area_km2,
    tiles_for,
    village_status,
)

YEARS = 14  # 2012-2025


def test_tiles_cover_every_box():
    # Kebbi sits in one tile; a box across 10°E touches the next tile east.
    assert tiles_for([(3.5, 10.5, 6.0, 13.3)]) == [(18, 7)]
    assert tiles_for([(9.5, 8.5, 10.2, 9.9)]) == [(18, 8), (19, 8)]
    assert tiles_for([(5.0, 9.8, 5.5, 10.3)]) == [(18, 7), (18, 8)]


def test_pixel_area_shrinks_with_latitude():
    a = pixel_area_km2(np.array([0.0, 60.0]))
    assert abs(a[0] - 0.2152) < 0.001
    assert abs(a[1] - a[0] / 2) < 0.001


def test_lga_sums_count_each_pixel_once_and_ignore_fill():
    ids = np.array([[0, 1, 1], [2, 2, 0]])
    rad = np.array([[5.0, 2.0, -999.9], [0.4, 3.0, 9.0]])
    area = np.array([1.0, 2.0])
    sums, lit, px = lga_sums(ids, rad, area, 3)
    assert list(sums) == [14.0, 2.0, 3.4]                   # fill counts as no light
    assert list(px) == [2, 2, 2]
    assert list(lit) == [3.0, 1.0, 2.0]                      # only pixels >= LIT_NW, by row area
    assert LIT_NW == 1.0


def _series(start, end):
    return [start] * 3 + [start] * (YEARS - 6) + [end] * 3


def test_gone_dark_needs_both_composites():
    near = [3.0, 2.8, 3.1, 3.0, 2.5, 2.0, 1.5, 1.0, 0.8, 0.6, 0.0, 0.0, 0.0, 0.0]
    allang = [3.2, 3.0, 3.3, 3.1, 2.8, 2.2, 1.8, 1.2, 0.9, 0.7, 0.3, 0.2, 0.0, 0.1]
    assert village_status(near, allang, 2012) == ("gone_dark", 2022)
    # all-angle still sees faint light: not called gone
    faint = allang[:-3] + [0.6, 0.7, 0.6]
    assert village_status(near, faint, 2012) == ("steady", None)


def test_gone_dark_needs_clear_light_at_the_start():
    near = _series(0.7, 0.0)
    assert village_status(near, near, 2012) == ("steady", None)


def test_newly_lit_needs_darkness_every_start_year():
    near = [0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.9, 1.1, 1.0, 1.2, 1.1, 1.3, 1.2, 1.4]
    assert village_status(near, near, 2012) == ("newly_lit", 2017)
    blip = [0.6] + near[1:]
    assert village_status(blip, blip, 2012) == ("steady", None)


def test_missing_years_are_unknown_not_dark():
    near = [3.0, 3.0, 3.0] + [3.0] * 8 + [None, None, None]
    assert village_status(near, near, 2012) == ("steady", None)


def test_short_series_is_steady():
    assert village_status([1.0] * 4, [1.0] * 4, 2012) == ("steady", None)


def test_gone_dark_means_no_light_in_each_of_the_last_three_years():
    # Faintly lit again in the third-last year: not "no light for three years"
    near = [1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.8, 0.7, 0.6, 0.5, 0.5, 0.6, 0.0, 0.0]
    allang = [1.5] * 3 + [1.0] * 8 + [0.3, 0.1, 0.1]
    assert village_status(near, allang, 2012) == ("steady", None)


def test_gone_dark_needs_light_every_start_year():
    near = [0.0, 2.0, 2.4] + [1.5] * 8 + [0.0, 0.0, 0.0]
    assert village_status(near, near, 2012) == ("steady", None)


def test_newly_lit_needs_light_every_recent_year():
    near = [0.0] * 3 + [0.0] * 8 + [1.8, 0.0, 1.9]
    assert village_status(near, near, 2012) == ("steady", None)


def test_since_year_is_within_the_record():
    near = [3.0, 3.0, 3.0] + [2.0] * 8 + [0.0, 0.0, 0.0]
    status, since = village_status(near, near, 2012)
    assert status == "gone_dark" and since == 2023
