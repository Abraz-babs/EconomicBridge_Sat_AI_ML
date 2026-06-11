"""GET /api/v1/predict/crop_disease/model_info — capability endpoint.

Drives the dashboard's model badge: capability (what the NEXT inference would
use) rather than per-row provenance, so a trained model reads TRAINED for
every tenant regardless of their stored rows' versions.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_model_info_returns_envelope_with_capability():
    r = client.get("/api/v1/predict/crop_disease/model_info")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["model_name"] == "crop_classifier_resnet50"
    # Locally the artifact exists → trained; without it → untuned/stub.
    # Either way version and mode must agree.
    assert data["model_version"] == f"0.1.0-{data['execution_mode']}"
    assert data["execution_mode"] in ("trained", "untuned", "stub")


def test_model_info_is_tenantless():
    """Capability is process-global — no tenant header required."""
    r = client.get("/api/v1/predict/crop_disease/model_info")
    assert r.status_code == 200
    assert r.json()["meta"]["tenant_id"] is None
