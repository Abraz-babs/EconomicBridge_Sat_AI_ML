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

import pytest
from fastapi.testclient import TestClient

from main import app


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


def test_predictions_rejects_limit_below_one(client) -> None:
    """Pydantic enforces ge=1, le=100 on the `limit` query param."""
    response = client.get(
        "/api/v1/cropguard/predictions?limit=0",
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert response.status_code == 422


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
