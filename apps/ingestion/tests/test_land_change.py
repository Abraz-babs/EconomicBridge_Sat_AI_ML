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
    """Picking purely by cloud would cluster the sample in one fine week and
    miss the peak the whole method rests on."""
    days = {date(2026, 7, 1 + i): 10.0 for i in range(30)}
    picked = lcs._pick_dates(days, 5)
    assert len(picked) == 5
    assert max((b - a).days for a, b in zip(picked, picked[1:])) <= 8


def test_the_clearest_day_in_each_stretch_wins():
    days = {date(2026, 7, 1 + i): 90.0 for i in range(30)}
    days[date(2026, 7, 3)] = 5.0
    days[date(2026, 7, 27)] = 4.0
    picked = lcs._pick_dates(days, 5)
    assert date(2026, 7, 3) in picked and date(2026, 7, 27) in picked


def test_a_cloudy_season_is_still_sampled_not_skipped():
    """A 60% scene gate left Makurdi with ZERO usable dates in the 2025 rains
    and FCT with one. An LGA the clouds sat on must still be looked at — and
    then reported as poorly observed, never as calm."""
    days = {date(2026, 7, 1 + i * 5): 97.0 for i in range(6)}
    assert len(lcs._pick_dates(days, 12)) == 6


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


def test_cropland_that_became_water_is_not_a_change():
    """Kaduna's only detection in the first Nigeria-wide pass was peak
    0.68 -> -0.18: a field that became open water. Given this platform's
    history with floods, that must never be filed as land conversion."""
    inside, n = _grids()
    prev = np.full((20, 20), 0.68, "float32")
    now = np.full((20, 20), -0.18, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert not lc.stopped_greening(prev, now, ok).any()
    assert not lc.became_bare(prev, now, ok).any()


def test_a_whole_lga_having_a_poorer_year_is_not_a_whole_lga_being_cleared():
    """Fewer clear looks, or a weaker rains, moves every pixel down together.
    Uncorrected that produced 1,370 false clusters over Bungudu."""
    inside, n = _grids()
    prev = np.full((40, 40), 0.70, "float32")
    now = np.full((40, 40), 0.28, "float32")     # the WHOLE LGA is down 0.42
    inside = np.ones((40, 40), dtype=bool)
    n = np.full((40, 40), lc.MIN_OBSERVATIONS, dtype="uint8")
    ok = lc.usable(inside, prev, now, n, n)

    assert lc.stopped_greening(prev, now, ok).all(), "uncorrected, everything fires"
    shift = lc.season_shift(prev, now, ok)
    assert shift == pytest.approx(-0.42, abs=1e-3)
    assert not lc.stopped_greening(prev, lc.corrected(now, shift), ok).any()


def test_a_patch_that_fell_further_than_its_lga_still_fires():
    """The correction must remove the season, not the signal."""
    inside = np.ones((40, 40), dtype=bool)
    n = np.full((40, 40), lc.MIN_OBSERVATIONS, dtype="uint8")
    prev = np.full((40, 40), 0.70, "float32")
    now = np.full((40, 40), 0.55, "float32")     # LGA-wide dip of 0.15
    now[10:20, 10:20] = 0.05                     # this patch collapsed
    ok = lc.usable(inside, prev, now, n, n)
    fired = lc.stopped_greening(prev, lc.corrected(now, lc.season_shift(prev, now, ok)), ok)
    assert fired[10:20, 10:20].all()
    assert fired.sum() == 100, "and nothing else"


def test_a_greener_season_is_never_corrected_for():
    """Correcting a GREENER season would manufacture detections."""
    inside = np.ones((40, 40), dtype=bool)
    n = np.full((40, 40), lc.MIN_OBSERVATIONS, dtype="uint8")
    prev = np.full((40, 40), 0.55, "float32")
    now = np.full((40, 40), 0.75, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.season_shift(prev, now, ok) == 0.0


def test_too_few_vegetated_pixels_means_no_correction():
    """An LGA that cannot state its own typical season is not guessed at."""
    inside = np.zeros((40, 40), dtype=bool)
    inside[:5, :5] = True
    n = np.full((40, 40), lc.MIN_OBSERVATIONS, dtype="uint8")
    prev = np.full((40, 40), 0.70, "float32")
    now = np.full((40, 40), 0.20, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.season_shift(prev, now, ok) == 0.0


# ─── Rivers, sandbanks and ponds are not land conversion ──────────────────


def test_ground_ever_seen_as_water_is_excluded():
    """Ten of thirteen errors in the first measured sample were river channel
    or sandbank — seven of them the same river through Shinkafi."""
    n_water = np.zeros((20, 20), dtype="uint8")
    n_water[10, 10] = 1                       # wet on exactly one date
    now = np.full((20, 20), 0.08, "float32")
    assert not lc.dry_land(n_water, now)[10, 10]


def test_the_bank_beside_a_channel_goes_too():
    """Bars sit just outside the wetted channel and move year to year."""
    n_water = np.zeros((40, 40), dtype="uint8")
    n_water[20, 20] = 2
    now = np.full((40, 40), 0.08, "float32")
    land = lc.dry_land(n_water, now)
    assert not land[20, 20 + lc.WATER_BUFFER_PX], "within the buffer"
    assert land[20, 20 + lc.WATER_BUFFER_PX + 2], "and not beyond it"


def test_water_is_judged_on_the_raw_peak_not_the_corrected_one():
    """A shift correction could otherwise lift genuinely negative water back
    over the line — which is how two ponds reached the first sample."""
    n_water = np.zeros((20, 20), dtype="uint8")
    raw = np.full((20, 20), -0.067, "float32")      # a pond, as measured
    assert not lc.dry_land(n_water, raw).any()


def test_dry_ground_is_kept():
    n_water = np.zeros((20, 20), dtype="uint8")
    now = np.full((20, 20), 0.06, "float32")        # a bare road surface
    assert lc.dry_land(n_water, now).all()


# ─── The third season: recorded, never enforced ───────────────────────────


def _spot(prior, prev, now):
    return lc.Hotspot(kind=lc.KIND_BARE, lon=4.0, lat=12.0, area_ha=2.0,
                      peak_prev=prev, peak_now=now, peak_prior=prior)


def test_ground_that_greened_two_years_running_is_marked_persistent():
    """A road goes green -> bare once and stays; a sandbar alternates."""
    assert _spot(0.55, 0.60, 0.05).persistent


def test_ground_that_only_greened_last_year_is_not():
    """The Shinkafi sandbars: bare two years back, green last year, bare now."""
    assert not _spot(0.32, 0.56, 0.11).persistent


def test_a_hotspot_with_no_third_season_is_not_claimed_persistent():
    """NaN means the archive gave us nothing, not that the ground was bare."""
    assert not _spot(float("nan"), 0.60, 0.05).persistent


def test_the_third_season_does_not_filter_anything():
    """It is evidence on the row, not a gate. Enforcing it would have discarded
    three of eight confirmed detections, the Aleiro construction pad included."""
    inside, n = _grids()
    prev = np.full((20, 20), 0.70, "float32")
    now = np.full((20, 20), 0.05, "float32")
    ok = lc.usable(inside, prev, now, n, n)
    assert lc.became_bare(prev, now, ok).all(), "fires regardless of prior years"


def test_the_prior_peak_is_measured_over_the_patch():
    mask = np.zeros((40, 40), dtype=bool)
    mask[0:10, 0:10] = True
    prev = np.full((40, 40), 0.70, "float32")
    now = np.full((40, 40), 0.05, "float32")
    prior = np.full((40, 40), np.nan, "float32")
    prior[0:10, 0:10] = 0.61
    spot = lc.find_hotspots(mask, kind=lc.KIND_BARE, transform=TF,
                            to_lonlat=_identity, prev=prev, now=now, prior=prior)[0]
    assert spot.peak_prior == pytest.approx(0.61, abs=1e-3)
    assert spot.persistent


# ─── The farmland measure ─────────────────────────────────────────────────


def _veg(peak_val, seen_val, shape=(100, 100), inside_all=True):
    inside = np.ones(shape, dtype=bool)
    if not inside_all:
        inside[:, 50:] = False
    peak = np.full(shape, peak_val, "float32")
    seen = np.full(shape, seen_val, dtype="uint8")
    return lc.season_vegetation(peak, seen, inside, season_year=2026,
                                pixel_ha=0.09, n_dates=12)


def test_land_that_greened_is_counted_in_hectares():
    v = _veg(0.65, 3)
    assert v.greened_ha == pytest.approx(900.0)      # 10,000 px x 0.09 ha
    assert v.observed_ha == pytest.approx(900.0)
    assert v.greened_fraction == pytest.approx(1.0)


def test_ground_that_never_greened_is_not_counted():
    assert _veg(0.12, 3).greened_ha == 0.0


def test_ONE_clear_look_is_enough_to_count_green():
    """This is what makes Abuja report farmland at all. The change detector
    needs three looks in BOTH seasons and stayed silent over FCT; seeing a
    pixel green once is positive evidence on its own."""
    v = _veg(0.65, 1)
    assert v.greened_ha > 0


def test_a_pixel_never_seen_is_not_counted_either_way():
    v = _veg(0.65, 0)
    assert v.observed_ha == 0.0
    assert v.greened_ha == 0.0
    assert v.greened_fraction == 0.0, "no division by zero when nothing was seen"


def test_greened_share_is_measured_against_what_was_SEEN():
    """Cloud must not be counted as bare ground — the LGA's full area is the
    wrong denominator and would understate farming wherever it was cloudy."""
    shape = (100, 100)
    inside = np.ones(shape, dtype=bool)
    peak = np.full(shape, 0.65, "float32")
    seen = np.zeros(shape, dtype="uint8")
    seen[:, :25] = 3                                  # only a quarter seen
    v = lc.season_vegetation(peak, seen, inside, season_year=2026,
                             pixel_ha=0.09, n_dates=12)
    assert v.observed_fraction == pytest.approx(0.25)
    assert v.greened_fraction == pytest.approx(1.0), "all of what was seen"


def test_only_land_inside_the_lga_counts():
    v = _veg(0.65, 3, inside_all=False)
    assert v.lga_ha == pytest.approx(450.0)


def test_cloud_can_only_push_the_figure_down_never_up():
    """The whole point of the one-sided test: it is a LOWER bound."""
    full = _veg(0.65, 3).greened_ha
    shape = (100, 100)
    inside = np.ones(shape, dtype=bool)
    peak = np.full(shape, 0.65, "float32")
    peak[:, 50:] = np.nan                             # half hidden by cloud
    seen = np.full(shape, 3, dtype="uint8")
    seen[:, 50:] = 0
    partial = lc.season_vegetation(peak, seen, inside, season_year=2026,
                                   pixel_ha=0.09, n_dates=12)
    assert partial.greened_ha < full


def test_change_is_measured_only_where_BOTH_seasons_were_seen():
    """Subtracting one lower bound from another measures the weather. Over
    FCT's Municipal Area Council the raw figures were 43,264 ha last season
    against 83,395 ha this one — which reads as farmland doubling and is very
    largely the 2025 rains having been clouded out."""
    shape = (100, 100)
    inside = np.ones(shape, dtype=bool)
    peak_now = np.full(shape, 0.65, "float32")
    peak_prev = np.full(shape, 0.65, "float32")      # identical farming
    seen_now = np.full(shape, 3, dtype="uint8")
    seen_prev = np.zeros(shape, dtype="uint8")
    seen_prev[:, :50] = 3                            # last year, half clouded

    raw_now = lc.season_vegetation(peak_now, seen_now, inside, season_year=2026,
                                   pixel_ha=0.09, n_dates=12)
    raw_prev = lc.season_vegetation(peak_prev, seen_prev, inside, season_year=2025,
                                    pixel_ha=0.09, n_dates=12)
    assert raw_now.greened_ha > raw_prev.greened_ha, "the misleading comparison"

    c = lc.like_for_like(peak_now, seen_now, peak_prev, seen_prev, inside,
                         pixel_ha=0.09)
    assert c.change_ha == 0.0, "like-for-like sees no change, because there is none"
    assert c.common_observed_ha == pytest.approx(450.0)


def test_real_farmland_loss_still_shows_like_for_like():
    """The correction must remove the cloud, not the signal."""
    shape = (100, 100)
    inside = np.ones(shape, dtype=bool)
    seen = np.full(shape, 3, dtype="uint8")
    peak_prev = np.full(shape, 0.65, "float32")
    peak_now = np.full(shape, 0.65, "float32")
    peak_now[:20, :] = 0.10                          # a fifth stopped greening
    c = lc.like_for_like(peak_now, seen, peak_prev, seen, inside, pixel_ha=0.09)
    assert c.change_ha == pytest.approx(-180.0)
    assert c.change_fraction == pytest.approx(-0.20, abs=1e-6)


def test_no_change_quoted_against_a_season_with_nothing_in_common():
    shape = (50, 50)
    inside = np.ones(shape, dtype=bool)
    peak = np.full(shape, 0.65, "float32")
    seen_now = np.full(shape, 3, dtype="uint8")
    seen_prev = np.zeros(shape, dtype="uint8")
    c = lc.like_for_like(peak, seen_now, peak, seen_prev, inside, pixel_ha=0.09)
    assert c.common_observed_ha == 0.0
    assert c.change_fraction == 0.0, "no division by zero"


def test_a_change_is_not_quoted_when_one_season_was_barely_seen():
    """A common footprint fixes 'seen vs not seen', not 'seen twice vs seen
    eight times'. FCT ran raw +93%, then +38.9% like-for-like, on a 2025
    season that was still barely looked at."""
    shape = (60, 60)
    inside = np.ones(shape, dtype=bool)
    peak = np.full(shape, 0.65, "float32")
    seen_now = np.full(shape, 8, dtype="uint8")
    seen_prev = np.ones(shape, dtype="uint8")        # seen once
    c = lc.like_for_like(peak, seen_now, peak, seen_prev, inside, pixel_ha=0.09)
    assert c.common_observed_ha > 0, "the area is still measured"
    assert not c.comparable, "but the change must not be quoted"


def test_a_change_IS_quoted_when_both_seasons_were_seen_properly():
    shape = (60, 60)
    inside = np.ones(shape, dtype=bool)
    peak = np.full(shape, 0.65, "float32")
    seen = np.full(shape, lc.MIN_OBSERVATIONS, dtype="uint8")
    assert lc.like_for_like(peak, seen, peak, seen, inside, pixel_ha=0.09).comparable


# ─── Promotion into the live feed ─────────────────────────────────────────


def _cand(**kw):
    base = dict(kind=lc.KIND_BARE, lon=4.3, lat=12.1, area_ha=2.0,
                peak_prev=0.60, peak_now=0.05, peak_prior=0.55,
                land_cover="crops")
    base.update(kw)
    return lc.Hotspot(**base)


def test_a_farmland_detection_that_greened_two_years_is_promoted():
    assert lcs.promotable(_cand(), observed=0.9)


def test_a_road_through_scrub_is_NOT_promoted():
    """The platform is for farmland. Trees and built-up are what the land-cover
    map gets reliably right, so excluding them is sound."""
    assert not lcs.promotable(_cand(land_cover="trees"), observed=0.9)
    assert not lcs.promotable(_cand(land_cover="built"), observed=0.9)
    assert not lcs.promotable(_cand(land_cover="water"), observed=0.9)


def test_the_weaker_class_is_NOT_promoted():
    """stopped_greening measured 2 real in 55 random points — crop rotation."""
    assert not lcs.promotable(_cand(kind=lc.KIND_STOPPED), observed=0.9)


def test_ground_that_did_not_green_two_years_running_is_NOT_promoted():
    """20% precision without persistence against 64% with it."""
    assert not lcs.promotable(_cand(peak_prior=0.10), observed=0.9)


def test_nothing_is_promoted_from_an_lga_the_clouds_hid():
    assert not lcs.promotable(_cand(), observed=0.2)


def test_each_promoted_detection_keeps_its_OWN_position():
    """The whole point: the old feed pinned every alert in an LGA to the same
    centroid, so the same place surfaced pass after pass."""
    spots = [_cand(lon=4.30, lat=12.10), _cand(lon=4.51, lat=12.44),
             _cand(lon=4.62, lat=12.03)]
    assert all(lcs.promotable(h, 0.9) for h in spots)
    assert len({(h.lon, h.lat) for h in spots}) == 3


def test_the_alert_card_explains_itself():
    """The old card read 'Land-surface change risk (LGA-level) near Suru:
    radar land-surface change 1.5σ'. A card that just says 'Augie - rangeland'
    tells an operator nothing."""
    h = _cand(land_cover="rangeland", peak_prev=0.60, peak_now=0.05)
    text = lcs.alert_text(h, "Augie", 2026)
    assert text.startswith("Land-surface change risk (patch-level) near Augie:")
    assert "rangeland" in text
    assert "2024 and 2025" in text
    assert "0.60 to 0.05" in text


def test_the_impact_figures_rest_on_the_MEASURED_patch():
    """Our area is the real patch, not an extent inferred from a severity
    band — so the livelihood figure is anchored to something measured."""
    assert round(12.0 * lcs.LIVELIHOODS_PER_HA) == 55
    assert round(12.0 * lcs.CROP_VALUE_NGN_PER_HA) == 2_400_000
