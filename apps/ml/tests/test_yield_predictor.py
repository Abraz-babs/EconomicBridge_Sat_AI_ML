"""Unit + router tests for the yield predictor (Slice 04.c).

The predictor's `_load_or_train` will train on synthetic data the first
time these tests run (no on-disk artifact). That training takes 1-2s on
the synthetic 4096-row dataset, which is fine for the unit-test budget.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from models.yield_predictor import (
    CROP_REFERENCE_MAX_T_HA,
    FEATURE_NAMES,
    YieldFeatures,
    get_predictor,
    hash_features,
)
from models.yield_training import (
    CROP_BASELINE_T_HA,
    generate_synthetic_dataset,
    train_synthetic_model,
)
from schemas.yield_predictor import SUPPORTED_CROPS


client = TestClient(app)


# ─── Feature ordering + dataclass contract ────────────────────────────────


def test_feature_names_count_matches_to_array_length():
    f = YieldFeatures(
        crop="maize", ndvi_mean_30d=0.5, ndvi_anomaly=0.0,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    assert f.to_array().shape == (len(FEATURE_NAMES),)


def test_features_crop_id_matches_supported_index():
    f = YieldFeatures(
        crop="rice", ndvi_mean_30d=0.5, ndvi_anomaly=0.0,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    assert f.crop_id() == SUPPORTED_CROPS.index("rice")


def test_features_rejects_unknown_crop():
    f = YieldFeatures(
        crop="quinoa", ndvi_mean_30d=0.5, ndvi_anomaly=0.0,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    with pytest.raises(ValueError, match="Unsupported crop"):
        f.crop_id()


def test_hash_features_is_deterministic():
    f1 = YieldFeatures(
        crop="maize", ndvi_mean_30d=0.5, ndvi_anomaly=0.1,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    f2 = YieldFeatures(
        crop="maize", ndvi_mean_30d=0.5, ndvi_anomaly=0.1,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    assert hash_features(f1) == hash_features(f2)


def test_reference_max_covers_every_supported_crop():
    for crop in SUPPORTED_CROPS:
        assert crop in CROP_REFERENCE_MAX_T_HA
        assert crop in CROP_BASELINE_T_HA
        assert CROP_BASELINE_T_HA[crop] < CROP_REFERENCE_MAX_T_HA[crop]


# ─── Synthetic dataset + training ─────────────────────────────────────────


def test_synthetic_dataset_shape():
    X, y = generate_synthetic_dataset(n_samples=256)
    assert X.shape == (256, len(FEATURE_NAMES))
    assert y.shape == (256,)
    assert (y >= 0).all()


def test_synthetic_dataset_deterministic_seed():
    X1, y1 = generate_synthetic_dataset(n_samples=128, seed=7)
    X2, y2 = generate_synthetic_dataset(n_samples=128, seed=7)
    assert (X1 == X2).all()
    assert (y1 == y2).all()


def test_train_synthetic_model_returns_fitted_regressor_and_explainer():
    reg, explainer = train_synthetic_model()
    assert reg.n_estimators == 160
    assert explainer is not None
    # Smoke: fitted estimator predicts something finite.
    X, _ = generate_synthetic_dataset(n_samples=16)
    preds = reg.predict(X)
    assert len(preds) == 16
    assert all(p >= 0 for p in preds)


# ─── Predictor end-to-end (no DB) ─────────────────────────────────────────


def test_predict_returns_canonical_model_prediction_and_yield_pi():
    p = get_predictor()
    f = YieldFeatures(
        crop="maize", ndvi_mean_30d=0.6, ndvi_anomaly=0.1,
        rainfall_30d_mm=180, rainfall_anomaly=0.05,
        soil_quality_index=0.55, historical_yield_mean_t_ha=2.2,
        days_to_harvest=60,
    )
    result, yield_t_ha, pi_low, pi_high = p.predict(tenant_id="kebbi", features=f)
    assert 0.0 <= result.prediction <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence_band in ("HIGH", "MEDIUM", "LOW")
    assert result.model_name == "yield_predictor"
    assert yield_t_ha >= 0
    assert pi_low is not None and pi_high is not None
    assert pi_low <= yield_t_ha <= pi_high


def test_predict_zero_history_forces_human_review():
    """CLAUDE.md §9: new geography (no history) ALWAYS needs review."""
    p = get_predictor()
    f = YieldFeatures(
        crop="cassava", ndvi_mean_30d=0.6, ndvi_anomaly=0.1,
        rainfall_30d_mm=180, rainfall_anomaly=0.0,
        soil_quality_index=0.55, historical_yield_mean_t_ha=0.0,   # new geo
        days_to_harvest=60,
    )
    result, _, _, _ = p.predict(tenant_id="kebbi", features=f)
    assert result.requires_human_review is True


def test_predict_shap_values_cover_every_feature():
    p = get_predictor()
    f = YieldFeatures(
        crop="rice", ndvi_mean_30d=0.5, ndvi_anomaly=0.0,
        rainfall_30d_mm=150, rainfall_anomaly=0.0,
        soil_quality_index=0.5, historical_yield_mean_t_ha=2.0,
        days_to_harvest=60,
    )
    result, _, _, _ = p.predict(tenant_id="kebbi", features=f)
    assert set(result.shap_values.keys()) == set(FEATURE_NAMES)


# ─── HTTP contract ───────────────────────────────────────────────────────


def _body(**overrides) -> dict:
    base = {
        "tenant_id": "kebbi",
        "crop": "maize",
        "ndvi_mean_30d": 0.6,
        "ndvi_anomaly": 0.05,
        "rainfall_30d_mm": 180.0,
        "rainfall_anomaly": 0.0,
        "soil_quality_index": 0.55,
        "historical_yield_mean_t_ha": 2.2,
        "days_to_harvest": 60,
        "persist": False,
    }
    base.update(overrides)
    return base


def test_predict_yield_returns_envelope_with_canonical_fields():
    response = client.post("/api/v1/predict/yield", json=_body())
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tenant_id"] == "kebbi"
    assert data["crop"] == "maize"
    assert 0.0 <= data["prediction"] <= 1.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["predicted_yield_t_ha"] >= 0
    assert data["yield_pi_low_t_ha"] is not None
    assert data["yield_pi_high_t_ha"] is not None
    assert data["yield_pi_low_t_ha"] <= data["yield_pi_high_t_ha"]
    assert set(data["shap_values"].keys()) == set(FEATURE_NAMES)
    assert data["persisted"] is False
    assert data["prediction_id"] is None


def test_predict_yield_unknown_tenant_returns_404():
    response = client.post("/api/v1/predict/yield", json=_body(tenant_id="atlantis"))
    assert response.status_code == 404


def test_predict_yield_unknown_crop_returns_400():
    response = client.post("/api/v1/predict/yield", json=_body(crop="quinoa"))
    assert response.status_code == 400
    # Slice 24: §7 envelope — message under error.message.
    assert "Unsupported crop" in response.json()["error"]["message"]


def test_predict_yield_rejects_ndvi_out_of_range():
    response = client.post("/api/v1/predict/yield", json=_body(ndvi_mean_30d=2.0))
    assert response.status_code == 422


def test_predict_yield_rejects_negative_rainfall():
    response = client.post("/api/v1/predict/yield", json=_body(rainfall_30d_mm=-50))
    assert response.status_code == 422


def test_predict_yield_rejects_unknown_fields():
    response = client.post("/api/v1/predict/yield", json=_body(mystery_field="x"))
    assert response.status_code == 422
