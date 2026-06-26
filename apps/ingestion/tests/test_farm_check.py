"""Unit tests for the Farm Check pure logic (no CDSE/network)."""
from __future__ import annotations

import sys
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from sources.farm_check import (  # noqa: E402
    bbox_around, classify_health, normalise_crop,
)


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
