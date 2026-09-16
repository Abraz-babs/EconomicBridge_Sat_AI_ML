"""Land-change classification — the decisions, on synthetic arrays.

Each test pins something that was learned by looking at real imagery, so a
future change to a threshold has to argue with the evidence rather than a
number someone liked.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from rasterio.transform import from_origin

from processors import land_change as lc
from tasks import land_change_scan as lcs

TF = from_origin(500_000.0, 1_340_000.0, 30.0, 30.0)   # 30 m grid, UTM-like


def _grids(shape=(20, 20)):
    inside = np.ones(shape, dtype=bool)
    n = np.full(shape, lc.MIN_OBSERVATIONS, dtype="uint8")
    return inside, n


def _identity(x, y):
    return x, y


# ─── What counts as a change ──────────────────────────────────────────────


def test_land_that_greened_both_years_is_not_a_change():
    """Crops green up again every season — that is the whole confounder."""
    inside, n = _grids()
    prev = np.full((20, 20), 0.80, "float32")
    now = np.full((20, 20), 0.75, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert not lc.stopped_greening(prev, now, ok).any()
    assert not lc.became_bare(prev, now, ok).any()


def test_green_last_season_and_bare_now_is_a_change():
    inside, n = _grids()
    prev = np.full((20, 20), 0.70, "float32")
    now = np.full((20, 20), 0.03, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.stopped_greening(prev, now, ok).all()
    assert lc.became_bare(prev, now, ok).all(), "also fully non-vegetated"


def test_the_stricter_rule_is_actually_stricter():
    """Sparse regrowth stopped greening but is not non-vegetated.

    Both rules firing on the same ground would make the high-confidence flag
    decorative. 0.15 is thin scrub, not a building site, and only the loose
    rule may claim it.
    """
    inside, n = _grids()
    prev = np.full((20, 20), 0.70, "float32")
    now = np.full((20, 20), 0.15, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.stopped_greening(prev, now, ok).all()
    assert not lc.became_bare(prev, now, ok).any()


def test_water_is_not_a_new_building():
    """A reservoir edge that dried reads negative; built ground does not."""
    inside, n = _grids()
    prev = np.full((20, 20), 0.85, "float32")
    now = np.full((20, 20), -0.09, "float32")       # open water
    ok = lc.usable(inside, prev, now, n, n)
    assert not lc.became_bare(prev, now, ok).any()


def test_ground_that_was_never_green_cannot_stop_greening():
    """The known blind spot, pinned: a real roadside structure went 0.36 -> 0.05
    and neither rule saw it. That needs radar, not a lower threshold."""
    inside, n = _grids()
    prev = np.full((20, 20), 0.20, "float32")       # bare before
    now = np.full((20, 20), 0.05, "float32")        # built after
    ok = lc.usable(inside, prev, now, n, n)
    assert not lc.stopped_greening(prev, now, ok).any()
    assert not lc.became_bare(prev, now, ok).any()


def test_a_pixel_the_clouds_hid_is_not_judged():
    """Too few clear looks must read as "not seen", never as "not green"."""
    inside, _ = _grids()
    prev = np.full((20, 20), 0.80, "float32")
    now = np.full((20, 20), 0.10, "float32")
    thin = np.full((20, 20), lc.MIN_OBSERVATIONS - 1, dtype="uint8")
    enough = np.full((20, 20), lc.MIN_OBSERVATIONS, dtype="uint8")
    assert not lc.usable(inside, prev, now, thin, enough).any()
    assert not lc.usable(inside, prev, now, enough, thin).any()


def test_only_pixels_inside_the_lga_count():
    inside, n = _grids()
    inside[:, 10:] = False
    prev = np.full((20, 20), 0.80, "float32")
    now = np.full((20, 20), 0.10, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.stopped_greening(prev, now, ok)[:, :10].all()
    assert not lc.stopped_greening(prev, now, ok)[:, 10:].any()


# ─── Hotspots carry their own position ────────────────────────────────────


def test_each_hotspot_reports_its_own_place_not_the_lga_centre():
    """The defect being replaced: every alert pinned to the LGA centroid."""
    mask = np.zeros((40, 40), dtype=bool)
    mask[2:8, 2:8] = True          # one patch, north-west
    mask[30:38, 30:38] = True      # another, south-east
    prev = np.full((40, 40), 0.8, "float32")
    now = np.full((40, 40), 0.1, "float32")
    spots = lc.find_hotspots(mask, kind=lc.KIND_STOPPED, transform=TF,
                             to_lonlat=_identity, prev=prev, now=now)
    assert len(spots) == 2
    assert spots[0].area_ha > spots[1].area_ha, "largest first"
    assert len({(s.lon, s.lat) for s in spots}) == 2, "different positions"


def test_area_is_measured_from_the_pixels():
    mask = np.zeros((40, 40), dtype=bool)
    mask[0:10, 0:10] = True                     # 10 x 10 px at 30 m = 9 ha
    prev = np.full((40, 40), 0.8, "float32")
    now = np.full((40, 40), 0.1, "float32")
    spots = lc.find_hotspots(mask, kind=lc.KIND_STOPPED, transform=TF,
                             to_lonlat=_identity, prev=prev, now=now, min_ha=0.5)
    assert spots[0].area_ha == pytest.approx(9.0, rel=1e-3)


def test_specks_are_not_reported():
    """Below ~1 ha at 30 m, speckle and field-edge slivers dominate."""
    mask = np.zeros((40, 40), dtype=bool)
    mask[5:7, 5:7] = True                       # 2 x 2 px = 0.36 ha
    prev = np.full((40, 40), 0.8, "float32")
    now = np.full((40, 40), 0.1, "float32")
    assert lc.find_hotspots(mask, kind=lc.KIND_STOPPED, transform=TF,
                            to_lonlat=_identity, prev=prev, now=now) == []


def test_a_hotspot_carries_the_greenness_either_side():
    mask = np.zeros((40, 40), dtype=bool)
    mask[0:10, 0:10] = True
    prev = np.full((40, 40), np.nan, "float32")
    now = np.full((40, 40), np.nan, "float32")
    prev[0:10, 0:10] = 0.77
    now[0:10, 0:10] = 0.08
    spot = lc.find_hotspots(mask, kind=lc.KIND_BARE, transform=TF,
                            to_lonlat=_identity, prev=prev, now=now)[0]
    assert spot.peak_prev == pytest.approx(0.77, abs=1e-3)
    assert spot.peak_now == pytest.approx(0.08, abs=1e-3)
    assert spot.kind == lc.KIND_BARE


def test_polygon_area_subtracts_holes():
    ring = [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]
    hole = [[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]]
    assert lc.polygon_area_m2({"coordinates": [ring]}) == pytest.approx(10_000)
    assert lc.polygon_area_m2({"coordinates": [ring, hole]}) == pytest.approx(9_600)


# ─── Season windows ───────────────────────────────────────────────────────


def test_both_years_use_the_same_calendar_window():
    """Otherwise the year given more weeks has more chances to peak."""
    a = lcs.wet_window(2025, date(2026, 9, 15))
    b = lcs.wet_window(2026, date(2026, 9, 15))
    assert (a[0].month, a[0].day) == (b[0].month, b[0].day)
    assert (a[1].month, a[1].day) == (b[1].month, b[1].day)
    assert a[0].year == 2025 and b[0].year == 2026


def test_the_window_never_runs_past_the_end_of_the_rains():
    w = lcs.wet_window(2026, date(2026, 12, 31))
    assert (w[1].month, w[1].day) == lcs.WET_END_CAP_MD


def test_a_run_before_the_rains_still_gets_a_usable_window():
    w = lcs.wet_window(2026, date(2026, 2, 1))
    assert w[1] > w[0]


def test_dates_are_spread_across_the_season_not_clustered():
    days = [date(2026, 7, 1 + i) for i in range(30)]
    picked = lcs._spread(days, 5)
    assert len(picked) == 5
    assert picked[0] == days[0] and picked[-1] == days[-1]


# ─── Surviving a free archive with no SLA ─────────────────────────────────


class _Scene:
    def __init__(self):
        from datetime import datetime, timezone
        self.assets = {"B04": "a", "B08": "b", "SCL": "c"}
        self.datetime = datetime(2026, 8, 2, tzinfo=timezone.utc)


async def test_a_transient_archive_failure_is_retried(monkeypatch):
    """Planetary Computer answers 503 under load; one hiccup must not cost an
    LGA an hour of reads."""
    from rasterio.errors import RasterioIOError

    calls = {"n": 0}

    def flaky(href, grid, resampling=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RasterioIOError("HTTP response code: 503")
        return np.ones((4, 4), dtype="float32")

    monkeypatch.setattr(lcs.cw, "read_on_grid", flaky)
    monkeypatch.setattr(lcs, "READ_BACKOFF_S", 0.0)
    out = await lcs._read_once("href", None, None)
    assert calls["n"] == 3
    assert out.shape == (4, 4)


async def test_a_date_the_archive_will_not_serve_is_dropped_not_fatal(monkeypatch):
    """Losing a date lowers the observation count, which usable() already
    guards. Losing the LGA loses the other two hundred behind it."""
    from rasterio.errors import RasterioIOError

    def always_503(href, grid, resampling=None):
        raise RasterioIOError("HTTP response code: 503")

    monkeypatch.setattr(lcs.cw, "read_on_grid", always_503)
    monkeypatch.setattr(lcs, "READ_BACKOFF_S", 0.0)

    async def href(collection, asset, **kw):
        return "signed"

    monkeypatch.setattr(lcs.oa, "signed_href", href)
    got = await lcs._ndvi_for_day([_Scene()], None, __import__("asyncio").Semaphore(1))
    assert got is None
