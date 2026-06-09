"""Unit tests for GET /api/v1/cropguard/predictions.

Two test paths:
  * Header/auth contract — runs without a live DB (fail-closed on missing
    or unknown X-Tenant-Id).
  * Integration — needs Postgres + migrations through 0014 + at least one
    row in tenant_kebbi.crop_predictions. Marked `integration`, skipped
    by default.

The full happy-path round-trip is also exercised indirectly by the ML
service's test_predict_crop_router.py (which writes the row this
endpoint reads).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.cropguard import _row_to_response
from scripts.seed_cropguard_predictions import TENANT_CROPS, _classes_for


# ─── Per-state crop realism (regression: Kebbi must not grow plantain) ─────

# Humid-zone crops that have no business in the arid NW states.
_HUMID_CROPS = ("plantain", "cassava")


def test_arid_states_have_no_humid_crops():
    for tenant in ("kebbi", "zamfara"):
        classes = _classes_for(tenant, 5)
        for c in classes:
            assert not c.startswith(_HUMID_CROPS), f"{tenant} got {c} — wrong for arid NW"


def test_seed_classes_stay_within_tenant_crop_profile():
    for tenant, crops in TENANT_CROPS.items():
        for c in _classes_for(tenant, 5):
            crop = c.split("_", 1)[0]
            assert crop in crops, f"{tenant} produced {c} outside its crop profile {crops}"


def test_humid_tenants_can_grow_plantain():
    # Ghana + Benue genuinely grow plantain — it should be allowed there.
    assert "plantain" in TENANT_CROPS["ghana"]
    assert "plantain" in TENANT_CROPS["benue"]


@pytest.fixture
def client():
    """Per-test TestClient so the asyncpg pool's event loop is isolated
    between tests. (Python 3.14 + asyncpg interact poorly when a single
    pool is shared across multiple TestClient calls in the same module.)"""
    with TestClient(app) as c:
        yield c


# ─── Tenant header contract (no DB needed) ─────────────────────────────────


def test_predictions_without_tenant_header_returns_400(client) -> None:
    response = client.get("/api/v1/cropguard/predictions")
    assert response.status_code == 400, response.text
    assert "X-Tenant-Id" in response.text


def test_predictions_with_unknown_tenant_returns_404(client) -> None:
    response = client.get(
        "/api/v1/cropguard/predictions",
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TENANT_NOT_FOUND"


def test_predictions_endpoint_declares_limit_constraints(client) -> None:
    """Static OpenAPI check: limit is declared 1..100 in the route signature.

    A runtime call with limit=0 would correctly fail Pydantic validation,
    but FastAPI resolves the `get_session` dependency at the same time —
    which opens an asyncpg connection (CI has no Postgres). Static check
    keeps the contract verified without forcing CI to be DB-aware."""
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/cropguard/predictions"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100
    assert limit["schema"]["default"] == 10


# ─── _row_to_response location mapping (DB-free row → CropPredictionRow) ───


def _base_prediction_row() -> dict:
    return {
        "id": uuid4(),
        "tenant_id": "kebbi",
        "predicted_class": "cassava_mosaic_disease",
        "prediction": 0.92,
        "confidence": 0.88,
        "confidence_band": "MEDIUM",
        "requires_human_review": True,
        "top_k": [
            {"class_name": "cassava_mosaic_disease", "probability": 0.88},
            {"class_name": "maize_streak_virus", "probability": 0.07},
        ],
        "image_source": "inline",
        "image_s3_key": None,
        "image_s3_bucket": None,
        "model_name": "crop_classifier",
        "model_version": "0.0.0-seed",
        "inference_time_ms": 55,
        "created_at": datetime.now(timezone.utc),
    }


def test_row_to_response_attaches_real_location() -> None:
    """ST_X/ST_Y(location) → a LonLat the map uses for the field marker."""
    row = _base_prediction_row() | {"lon": 4.52, "lat": 12.74}
    pred = _row_to_response(row)
    assert pred.location is not None
    assert (pred.location.lon, pred.location.lat) == (4.52, 12.74)
    assert pred.predicted_class == "cassava_mosaic_disease"
    assert len(pred.top_k) == 2


def test_row_to_response_location_none_when_no_gps() -> None:
    """An upload with no GPS (lon/lat NULL) yields location=None so the map
    synthesises a position rather than failing."""
    row = _base_prediction_row() | {"lon": None, "lat": None}
    pred = _row_to_response(row)
    assert pred.location is None


# ─── Integration: real DB round-trip ──────────────────────────────────────


pytestmark_integration = pytest.mark.integration


@pytestmark_integration
def test_predictions_happy_path_returns_envelope(client) -> None:
    response = client.get(
        "/api/v1/cropguard/predictions",
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert "predictions" in body["data"]
    assert isinstance(body["data"]["predictions"], list)
    meta = body["meta"]
    assert meta["trace_id"]


@pytestmark_integration
def test_predictions_respects_limit(client) -> None:
    response = client.get(
        "/api/v1/cropguard/predictions?limit=2",
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["predictions"]) <= 2


@pytestmark_integration
def test_predictions_newest_first(client) -> None:
    response = client.get(
        "/api/v1/cropguard/predictions",
        headers={"X-Tenant-Id": "kebbi"},
    )
    rows = response.json()["data"]["predictions"]
    if len(rows) >= 2:
        for prev, nxt in zip(rows, rows[1:]):
            assert prev["created_at"] >= nxt["created_at"]
