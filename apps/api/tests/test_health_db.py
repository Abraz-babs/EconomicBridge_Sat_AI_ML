"""Integration tests for GET /api/v1/health/db.

Skipped by default. Run with: `pytest -m integration`. CI runs these against a
real database (Postgres + PostGIS) and they must pass before deploy.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


def test_health_db_returns_envelope_with_server_version() -> None:
    response = client.get("/api/v1/health/db")

    # If migrations have not been run, the connection itself may succeed but
    # there's still no schema to query. The endpoint only runs SHOW + pg_extension,
    # which work on an empty DB, so 200 is expected.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["server_version"]
    # Booleans for extension presence
    assert isinstance(body["data"]["has_postgis"], bool)
    assert isinstance(body["data"]["has_timescaledb"], bool)


def test_health_db_response_uses_envelope_meta() -> None:
    response = client.get("/api/v1/health/db")
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["trace_id"]
    assert meta["timestamp"]
    assert meta["tenant_id"] is None
