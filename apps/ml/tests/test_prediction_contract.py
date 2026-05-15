"""Unit tests for the ModelPrediction dataclass + confidence routing.

These verify the CLAUDE.md §9 contract: thresholds, banding, and the
self-consistency check between `confidence` and `confidence_band`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.prediction import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    ModelPrediction,
    band_for_confidence,
)


def _now():
    return datetime.now(timezone.utc)


def test_band_high_above_high_threshold() -> None:
    assert band_for_confidence(0.90) == "HIGH"
    assert band_for_confidence(0.95) == "HIGH"
    assert band_for_confidence(0.999) == "HIGH"


def test_band_medium_between_thresholds() -> None:
    assert band_for_confidence(0.75) == "MEDIUM"
    assert band_for_confidence(0.80) == "MEDIUM"
    assert band_for_confidence(0.8999) == "MEDIUM"


def test_band_low_below_medium_threshold() -> None:
    assert band_for_confidence(0.0) == "LOW"
    assert band_for_confidence(0.5) == "LOW"
    assert band_for_confidence(0.7499) == "LOW"


def test_thresholds_are_the_claude_md_values() -> None:
    assert HIGH_THRESHOLD == 0.90
    assert MEDIUM_THRESHOLD == 0.75


def test_modelprediction_rejects_out_of_range_prediction() -> None:
    with pytest.raises(ValueError, match="prediction"):
        ModelPrediction(
            model_name="x", model_version="0", tenant_id="kebbi",
            prediction=1.5, confidence=0.9,
            shap_values={}, input_hash="abc", inference_time_ms=1,
            timestamp=_now(),
            requires_human_review=False,
            confidence_band="HIGH",
        )


def test_modelprediction_rejects_mismatched_band() -> None:
    with pytest.raises(ValueError, match="does not match"):
        ModelPrediction(
            model_name="x", model_version="0", tenant_id="kebbi",
            prediction=0.7, confidence=0.5,            # LOW
            shap_values={}, input_hash="abc", inference_time_ms=1,
            timestamp=_now(),
            requires_human_review=True,
            confidence_band="HIGH",                    # mismatch
        )


def test_modelprediction_accepts_consistent_values() -> None:
    p = ModelPrediction(
        model_name="x", model_version="0", tenant_id="kebbi",
        prediction=0.8, confidence=0.92,
        shap_values={"f1": 0.1}, input_hash="abc",
        inference_time_ms=5, timestamp=_now(),
        requires_human_review=False,
        confidence_band="HIGH",
    )
    assert p.confidence_band == "HIGH"
    assert p.requires_human_review is False
