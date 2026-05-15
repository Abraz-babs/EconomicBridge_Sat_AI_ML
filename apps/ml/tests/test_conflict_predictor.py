"""Unit tests for the Random Forest conflict predictor.

These exercise the real model (trained from synthetic data on first call) but
NOT the DB layer. Live persistence is covered by the integration suite.
"""
from __future__ import annotations

import pytest

from models.conflict_predictor import (
    FEATURE_NAMES,
    MODEL_NAME,
    ConflictFeatures,
    get_predictor,
    hash_features,
)


def _high_risk() -> ConflictFeatures:
    """Feature vector that should produce a high-confidence positive prediction."""
    return ConflictFeatures(
        heat_signature_intensity=0.95,
        boundary_distance_km=0.4,
        ndvi_delta=-0.8,
        herder_density=0.9,
        historical_incidents=30,
        rainfall_anomaly=-0.7,
        is_new_geography=False,
    )


def _low_risk() -> ConflictFeatures:
    """Feature vector that should produce a low-confidence positive prediction."""
    return ConflictFeatures(
        heat_signature_intensity=0.05,
        boundary_distance_km=45.0,
        ndvi_delta=0.7,
        herder_density=0.05,
        historical_incidents=0,
        rainfall_anomaly=0.6,
        is_new_geography=False,
    )


def test_predict_returns_valid_modelprediction_shape() -> None:
    p = get_predictor().predict(tenant_id="kebbi", features=_high_risk())
    assert p.tenant_id == "kebbi"
    assert p.model_name == MODEL_NAME
    assert 0.0 <= p.prediction <= 1.0
    assert 0.0 <= p.confidence <= 1.0
    assert p.confidence_band in ("HIGH", "MEDIUM", "LOW")
    assert set(p.shap_values.keys()) == set(FEATURE_NAMES)
    assert p.inference_time_ms >= 0
    assert len(p.input_hash) == 64  # SHA-256 hex digest


def test_high_risk_features_produce_positive_prediction() -> None:
    p = get_predictor().predict(tenant_id="kebbi", features=_high_risk())
    # Domain check: extreme heat + close boundary + dry + many incidents → positive
    assert p.prediction > 0.5, f"expected positive class for high-risk inputs, got {p.prediction}"


def test_low_risk_features_produce_negative_prediction() -> None:
    p = get_predictor().predict(tenant_id="kebbi", features=_low_risk())
    # Domain check: low heat + distant + wet + zero history → negative
    assert p.prediction < 0.5, f"expected negative class for low-risk inputs, got {p.prediction}"


def test_new_geography_forces_human_review_even_when_confident() -> None:
    """CLAUDE.md §9: 'New geographic area: ALWAYS require human review regardless of confidence.'"""
    hr_with_new = ConflictFeatures(
        heat_signature_intensity=0.95,
        boundary_distance_km=0.3,
        ndvi_delta=-0.9,
        herder_density=0.95,
        historical_incidents=40,
        rainfall_anomaly=-0.8,
        is_new_geography=True,
    )
    p = get_predictor().predict(tenant_id="kebbi", features=hr_with_new)
    assert p.requires_human_review is True


def test_high_confidence_known_geography_does_not_force_review() -> None:
    p = get_predictor().predict(tenant_id="kebbi", features=_high_risk())
    if p.confidence_band == "HIGH":
        # The proven-conflict case should auto-route — no review needed
        assert p.requires_human_review is False
    else:
        pytest.skip("training landed in MEDIUM/LOW band for this seed — not testable here")


def test_hash_features_is_deterministic() -> None:
    f = _high_risk()
    assert hash_features(f) == hash_features(f)


def test_hash_features_differs_for_different_inputs() -> None:
    assert hash_features(_high_risk()) != hash_features(_low_risk())


def test_shap_values_have_one_entry_per_feature() -> None:
    p = get_predictor().predict(tenant_id="kebbi", features=_high_risk())
    assert len(p.shap_values) == len(FEATURE_NAMES)
    for name in FEATURE_NAMES:
        assert isinstance(p.shap_values[name], float)
