"""Unit tests for the Farm Check pure logic (no CDSE/network)."""
from __future__ import annotations

import sys
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from datetime import datetime, timezone  # noqa: E402

from sources.farm_check import (  # noqa: E402
    assess_stress, bbox_around, classify_health, latest_usable_pass,
    normalise_crop,
)


def test_assess_stress_flags_decline():
    # Stable ~0.6 then a sharp recent drop -> significant stress.
    s = assess_stress([0.61, 0.60, 0.62, 0.59, 0.30, 0.28])
    assert s["level"] in ("high", "moderate")
    assert s["z"] < 0


def test_assess_stress_no_signal_when_stable_or_rising():
    s = assess_stress([0.39, 0.35, 0.40, 0.56])  # greening field
    assert s["level"] == "none"


def test_assess_stress_unknown_when_too_few_passes():
    s = assess_stress([0.5, 0.5])
    assert s["level"] == "unknown"
    assert s["z"] is None
from sources.sentinel_statistical import StatPoint  # noqa: E402


def _pt(day: int, mean: float | None, count: int) -> StatPoint:
    dt = datetime(2026, 6, day, tzinfo=timezone.utc)
    return StatPoint(
        interval_from=dt, interval_to=dt, dataset="sentinel-2-l2a",
        band_name="default", mean=mean, min_value=None, max_value=None,
        std_dev=None, sample_count=count,
    )


def test_latest_usable_prefers_recent_pass_with_enough_clear_pixels():
    # June 25 is the latest and has 200/480 = 42% clear (>= 25%) -> chosen.
    pts = [_pt(2, 0.04, 480), _pt(12, 0.30, 470), _pt(25, 0.02, 200)]
    chosen = latest_usable_pass(pts)
    assert chosen is not None and chosen.interval_from.day == 25
    assert chosen.mean == 0.02


def test_latest_usable_skips_mostly_clouded_latest():
    # June 25 has only 20/480 = 4% clear -> skip it, fall back to the clear June 2.
    pts = [_pt(2, 0.04, 480), _pt(25, 0.9, 20)]
    chosen = latest_usable_pass(pts)
    assert chosen is not None and chosen.interval_from.day == 2


def test_latest_usable_none_when_no_valid():
    assert latest_usable_pass([]) is None
    assert latest_usable_pass([_pt(5, None, 0)]) is None


def test_normalise_crop_synonyms_and_case():
    assert normalise_crop("  Corn ") == "maize"
    assert normalise_crop("MAIZE") == "maize"
    assert normalise_crop("Guinea Corn") == "sorghum"
    assert normalise_crop(None) == ""


def test_classify_none_is_unknown():
    health, verdict = classify_health(None, "maize")
    assert health == "unknown"
    assert "cloud-free" in verdict.lower()


def test_classify_bare_soil():
    health, _ = classify_health(0.08, "maize")
    assert health == "bare"


def test_classify_healthy_for_crop():
    # maize peak ~0.72; 0.70 is ~0.97 of peak -> healthy
    health, verdict = classify_health(0.70, "maize")
    assert health == "healthy"
    assert "maize" in verdict


def test_classify_is_crop_aware():
    # Same NDVI, different verdict by crop: 0.55 is moderate for maize
    # (peak .72 → ratio .76) but healthy for millet (peak .58 → ratio .95).
    maize_health, _ = classify_health(0.55, "maize")
    millet_health, _ = classify_health(0.55, "millet")
    assert maize_health == "moderate"
    assert millet_health == "healthy"
    assert maize_health != millet_health   # crop-aware


def test_classify_unknown_crop_uses_default_peak():
    # Unknown crop -> default peak 0.70; NDVI 0.66 -> ~0.94 -> healthy
    health, _ = classify_health(0.66, "dragonfruit")
    assert health in ("healthy", "moderate")


def test_bbox_around_is_centred_and_ordered():
    w, s, e, n = bbox_around(9.07, 7.48, 120)  # near Abuja
    assert w < 7.48 < e
    assert s < 9.07 < n
    # ~240 m box → well under 0.01° in each dimension
    assert (e - w) < 0.01 and (n - s) < 0.01
    assert (e - w) > 0 and (n - s) > 0


from sources.farm_check import is_general_crop  # noqa: E402


def test_is_general_crop_detects_blank_and_general():
    for c in ("", "  ", "general", "General", "mixed", "unknown", None):
        assert is_general_crop(c)
    # A named crop and the per-LGA sweep tag stay crop-aware (NOT general):
    assert not is_general_crop("maize")
    assert not is_general_crop("cropland")


def test_classify_general_uses_absolute_ndvi_bands():
    # No crop given → crop-agnostic absolute NDVI bands.
    assert classify_health(0.65, "general")[0] == "healthy"
    assert classify_health(0.50, "general")[0] == "moderate"
    assert classify_health(0.30, "general")[0] == "stressed"
    assert classify_health(0.18, "general")[0] == "poor"
    assert classify_health(0.05, "general")[0] == "bare"
    assert classify_health(0.65, "")[0] == "healthy"  # blank == general


def test_general_does_not_change_named_crop_verdicts():
    # Regression: named crops graded exactly as before; "cropland" (LGA sweep)
    # keeps the default-peak path, not the general bands.
    assert classify_health(0.70, "maize")[0] == "healthy"
    assert classify_health(0.66, "cropland")[0] in ("healthy", "moderate")
