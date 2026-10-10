"""Pre-season risk profile: the season, onset and band rules, tile naming, the PNG writer."""
from __future__ import annotations

import struct
import zlib
from datetime import date

import numpy as np

from tasks.risk_profile import (
    drought_band, dryspell_band, failed_rains, find_onset, flood_band, jrc_tile_names,
    longest_dry_run, png_gray, season_stats, worldcover_tile_names,
)

WINDOW = date(2001, 3, 1)


def _monthly(years, per_month, scale=None):
    scale = scale or {}
    return {(y, m): per_month.get(m, 0.0) * scale.get(y, 1.0) for y in years for m in range(3, 12)}


def test_season_is_the_wet_months_and_drought_is_below_80_percent_of_normal():
    years = list(range(1991, 2026))
    data = _monthly(years, {5: 60.0, 6: 100.0, 7: 200.0, 8: 250.0, 9: 120.0, 10: 30.0},
                    scale={2013: 0.7, 2016: 0.79, 2020: 1.3})
    s = season_stats(data, years)
    assert s["season_months"] == [5, 6, 7, 8, 9]            # October averages 30 mm: not in the season
    assert s["normal_mm"] == 730.0
    assert s["drought_seasons"] == [2013, 2016]               # 70% and 79% of normal; 80% exactly is not
    assert s["worst"] == {"year": 2013, "pct_of_normal": 70.0}
    assert s["totals"]["2020"] == 949.0


def test_longest_dry_run_counts_days_under_1mm():
    rain = np.array([0, 0.5, 3, 0, 0, 0, 0.9, 2, 0])
    assert longest_dry_run(rain, 0, len(rain)) == 4
    assert longest_dry_run(rain, 3, 6) == 3
    assert longest_dry_run(rain, 7, 100) == 1


def _season(onset_at=None, false_start_at=None, dry_after=None, n=245):
    """A daily window (1 March onward) with rain every other day from onset."""
    r = np.zeros(n)
    if false_start_at is not None:
        r[false_start_at:false_start_at + 2] = 15.0          # 30 mm, then nothing for weeks
    if onset_at is not None:
        r[onset_at:n:2] = 8.0
        r[onset_at] = 25.0
    if dry_after is not None:
        lo, length = dry_after
        r[lo:lo + length] = 0.0
    return r


def test_onset_needs_20mm_in_three_days_and_no_long_dry_spell_after():
    r = _season(onset_at=92)                                   # 1 June
    assert find_onset(r, 61, 152) == (92, False)


def test_rain_followed_by_a_long_dry_spell_is_a_false_start():
    r = _season(onset_at=100, false_start_at=70)
    onset, false_start = find_onset(r, 61, 152)
    assert onset == 100 and false_start


def test_no_onset_when_the_rains_never_settle():
    assert find_onset(_season(false_start_at=70), 61, 152) == (None, True)


def test_failed_rains_per_year():
    daily = {
        2001: _season(onset_at=92),                            # normal season
        2002: _season(onset_at=92, false_start_at=65),         # false start
        2003: _season(onset_at=92, dry_after=(92 + 40, 12)),   # 12-day dry spell at flowering
        2004: _season(onset_at=125),                           # 33 days late
        2005: _season(onset_at=93),
    }
    missing = _season(onset_at=92)
    missing[10] = np.nan
    daily[2006] = missing                                      # a missing day: the year is left out
    out = failed_rains(daily, WINDOW, [5, 6, 7, 8, 9])
    assert out["years"] == [2001, 2002, 2003, 2004, 2005]
    assert out["false_starts"] == [2002]
    assert out["long_dry_spells"] == [2003]
    assert out["late_onsets"] == [2004]
    assert out["failed_seasons"] == [2002, 2003, 2004]
    assert out["onsets"]["2001"] == "2001-06-01"
    assert out["onset_median"] == "06-01"


def test_flood_band_rule():
    assert flood_band(10.0, 12.0, 0.0) == "high"
    assert flood_band(2.0, 2.5, 5.0) == "high"                 # mapped water alone can make it High
    assert flood_band(9.9, 3.0, 0.5) == "moderate"
    assert flood_band(0.5, 0.6, 1.0) == "moderate"
    assert flood_band(0.5, 2.9, 0.9) == "low"
    assert flood_band(None, None, None) == "none"
    assert flood_band(0.4, 0.5, None) == "low"                 # a country with no mapped floods


def test_share_bands():
    assert drought_band(7, 35) == "high"                       # 1 in 5
    assert drought_band(4, 35) == "moderate"                   # 1 in 10 or more
    assert drought_band(3, 35) == "low"
    assert drought_band(0, 0) == "none"
    assert dryspell_band(10, 28) == "high"                     # 1 in 3 or more
    assert dryspell_band(6, 28) == "moderate"
    assert dryspell_band(5, 28) == "low"


def test_jrc_tiles_for_our_pilots():
    assert jrc_tile_names((3.43, 10.05, 6.25, 13.31)) == ["N20_W0"]                       # Kebbi
    assert sorted(jrc_tile_names((-3.31, 4.69, 1.25, 11.22))) == ["N10_W0", "N10_W10", "N20_W0", "N20_W10"]
    assert jrc_tile_names((-17.58, 12.26, -11.30, 16.74)) == ["N20_W20"]                  # Senegal
    assert sorted(jrc_tile_names((8.50, 8.32, 10.69, 10.43))) == ["N10_E10", "N10_W0", "N20_E10", "N20_W0"]


def test_worldcover_tiles():
    assert worldcover_tile_names((3.43, 10.05, 6.25, 13.31)) == ["N09E003", "N09E006", "N12E003", "N12E006"]
    assert worldcover_tile_names((-1.0, 5.0, 0.5, 5.5)) == ["N03W003", "N03E000"]


def test_png_is_a_valid_greyscale_image():
    img = np.zeros((3, 4), dtype=np.uint8)
    img[1, 2] = 255
    png = png_gray(img)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, colour = struct.unpack(">IIBB", png[16:26])
    assert (w, h, depth, colour) == (4, 3, 8, 0)
    idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
    rows = zlib.decompress(idat)
    assert len(rows) == 3 * (1 + 4) and rows[5 + 1 + 2] == 255


def test_a_refusal_pauses_every_reader_and_slows_the_pace_once():
    from tasks.risk_profile import _Pace

    p = _Pace(2.0)
    assert p.rate() == 2.0
    assert p.blocked(cool_down=300) is True              # first report: slow down by a third
    assert abs(p.rate() - 2.0 / 1.5) < 1e-9
    assert p.blocked(cool_down=300) is False             # other readers hitting the same block
    assert abs(p.rate() - 2.0 / 1.5) < 1e-9              # ... do not slow it again
    import time
    assert p.next - time.monotonic() > 290               # everyone waits out the cool-down
    for _ in range(20):
        p.blocked(cool_down=0.0)
    assert p.rate() >= 0.25                              # never slower than the floor
