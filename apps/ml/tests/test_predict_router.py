"""Tests for POST /api/v1/predict/conflict.

The `persist=False` branch is covered by default-run unit tests (no DB needed
for inference itself — only DB writes are mocked away by setting persist
False). The `persist=True` round-trip is integration-only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _high_risk_body(*, persist: bool = False) -> dict:
    return {
        "tenant_id": "kebbi",
        "heat_signature_intensity": 0.95,
        "boundary_distance_km": 0.4,
        "ndvi_delta": -0.8,
        "herder_density": 0.9,
        "historical_incidents": 30,
        "rainfall_anomaly": -0.7,
        "is_new_geography": False,
        "persist": persist,
    }


def test_predict_returns_envelope_with_prediction_data() -> None:
    response = client.post("/api/v1/predict/conflict", json=_high_risk_body())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["tenant_id"] == "kebbi"
    assert 0.0 <= data["prediction"] <= 1.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["confidence_band"] in ("HIGH", "MEDIUM", "LOW")
    assert data["persisted"] is False
    assert data["prediction_id"] is None
    assert len(data["shap_values"]) == 7


def test_predict_unknown_tenant_returns_404() -> None:
    body = _high_risk_body()
    body["tenant_id"] = "atlantis"
    response = client.post("/api/v1/predict/conflict", json=body)
    assert response.status_code == 404


def test_predict_validates_feature_ranges() -> None:
    body = _high_risk_body()
    body["heat_signature_intensity"] = 5.0  # out of [0, 1]
    response = client.post("/api/v1/predict/conflict", json=body)
    assert response.status_code == 422


def test_predict_rejects_unknown_fields() -> None:
    body = _high_risk_body()
    body["mystery_field"] = "x"
    response = client.post("/api/v1/predict/conflict", json=body)
    assert response.status_code == 422


@pytest.mark.integration
def test_predict_persists_row_to_conflict_predictions() -> None:
    """Live DB round-trip: persist + read back the row that was written."""
    import json
    from sqlalchemy import create_engine, text
    from config import get_settings

    response = client.post(
        "/api/v1/predict/conflict", json=_high_risk_body(persist=True)
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["persisted"] is True
    assert body["prediction_id"]

    sync_url = get_settings().database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    )
    engine = create_engine(sync_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            row = conn.execute(
                text(
                    "SELECT model_name, model_version, confidence_band, "
                    "requires_human_review, shap_values "
                    "FROM conflict_predictions WHERE id = :id"
                ),
                {"id": body["prediction_id"]},
            ).one()
            assert row.model_name == "conflict_predictor"
            assert row.confidence_band == body["confidence_band"]
            shap = row.shap_values if isinstance(row.shap_values, dict) else json.loads(row.shap_values)
            assert set(shap.keys()) == set(body["shap_values"].keys())
        # Cleanup
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            conn.execute(
                text("DELETE FROM conflict_predictions WHERE id = :id"),
                {"id": body["prediction_id"]},
            )
    finally:
        engine.dispose()
