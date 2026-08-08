"""Crop-prior gating and abstention.

Context: the classifier learned a shortcut — maize and tomato came from
laboratory imagery, cassava and rice and plantain from field-collected sets, so
photographic STYLE predicts the crop before any leaf is examined. On a real
maize field photo it returned cassava_healthy at 0.770.

These guards do not make the model better. They stop it asserting a crop the
operator did not photograph, and stop it answering at all when it plainly does
not recognise what it was given. Both are pure functions of the probability
vector, so they are tested directly rather than through inference.
"""
from __future__ import annotations

import pytest

from models.crop_classifier import (
    CROP_CLASSES,
    MIN_CONFIDENCE_WITHOUT_CROP,
    MIN_CROP_MASS,
    SUPPORTED_CROPS,
    crop_of,
    normalise_crop,
)


def test_every_class_maps_to_a_supported_crop():
    """The prefix convention IS the mapping — a class named without one would
    silently become its own crop and never match a declaration."""
    for c in CROP_CLASSES:
        assert crop_of(c) in SUPPORTED_CROPS, c


def test_the_five_crops_are_discovered_from_the_class_list():
    assert set(SUPPORTED_CROPS) == {
        "cassava", "maize", "rice", "tomato", "plantain",
    }


@pytest.mark.parametrize("raw,expected", [
    ("maize", "maize"),
    ("Maize", "maize"),
    ("  MAIZE  ", "maize"),
    ("corn", "maize"),          # what a Nigerian field officer may well type
    ("manioc", "cassava"),
    ("yuca", "cassava"),
    ("banana", "plantain"),
    ("paddy", "rice"),
    ("tomatoes", "tomato"),
])
def test_free_text_crop_names_are_accepted(raw, expected):
    """The dashboard field is free text, so usable answers must not be thrown
    away over spelling or case."""
    assert normalise_crop(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "sorghum", "millet", "asdf"])
def test_unknown_or_absent_crop_is_none_never_a_guess(raw):
    """Sorghum and millet are real crops we do NOT classify. Guessing the
    nearest supported one would be worse than admitting we cannot help."""
    assert normalise_crop(raw) is None


# ─── the gating arithmetic, as predict() applies it ──────────────────────

def _mass(probs: dict[str, float], crop: str) -> float:
    return sum(p for c, p in probs.items() if crop_of(c) == crop)


def _renormalised(probs: dict[str, float], crop: str) -> dict[str, float]:
    masked = {c: (p if crop_of(c) == crop else 0.0) for c, p in probs.items()}
    total = sum(masked.values())
    return {c: p / total for c, p in masked.items()} if total else masked


def test_the_real_failure_case_abstains():
    """The measured failure: a maize field photo answered cassava_healthy 0.770
    while every maize class together held almost nothing."""
    probs = {c: 0.0 for c in CROP_CLASSES}
    probs["cassava_healthy"] = 0.770
    probs["cassava_mosaic_disease"] = 0.180
    probs["maize_healthy"] = 0.020
    probs["maize_northern_blight"] = 0.015
    probs["rice_blast"] = 0.015

    mass = _mass(probs, "maize")

    assert mass == pytest.approx(0.035)
    assert mass < MIN_CROP_MASS, "must abstain rather than name a maize disease"


def test_a_confident_in_crop_answer_is_still_returned():
    """Gating must not suppress the case the model actually handles."""
    probs = {c: 0.0 for c in CROP_CLASSES}
    probs["maize_northern_blight"] = 0.880
    probs["maize_healthy"] = 0.090
    probs["cassava_healthy"] = 0.030

    assert _mass(probs, "maize") >= MIN_CROP_MASS
    top = max(_renormalised(probs, "maize").items(), key=lambda kv: kv[1])
    assert top[0] == "maize_northern_blight"


def test_renormalising_reports_confidence_within_the_declared_crop():
    """0.30 of the whole vector but 0.75 among maize classes should read as
    0.75 — the operator asked about maize, not about everything."""
    probs = {c: 0.0 for c in CROP_CLASSES}
    probs["maize_northern_blight"] = 0.30
    probs["maize_healthy"] = 0.10
    probs["cassava_healthy"] = 0.60

    r = _renormalised(probs, "maize")

    assert r["maize_northern_blight"] == pytest.approx(0.75)
    assert r["cassava_healthy"] == 0.0
    assert sum(r.values()) == pytest.approx(1.0)


def test_threshold_sits_in_the_measured_gap_between_the_two_domains():
    """Calibrated 2026-08-08 with the trained weights on the very images that
    produced 12/12 and 0/3.

        laboratory  0.8601 .. 0.9996
        field       0.0094 .. 0.1699

    The threshold must sit strictly inside the empty band. The original 0.15 did
    NOT — it was below the field maximum, and a field photo at 0.1699 answered
    maize_streak_virus. These bounds are the measurement, so moving the constant
    back into either domain fails here rather than in someone's field.
    """
    FIELD_MAX = 0.1699
    LAB_MIN = 0.8601

    assert FIELD_MAX < MIN_CROP_MASS < LAB_MIN


def test_a_refusal_is_cheaper_than_a_wrong_answer():
    assert MIN_CONFIDENCE_WITHOUT_CROP >= 0.5
