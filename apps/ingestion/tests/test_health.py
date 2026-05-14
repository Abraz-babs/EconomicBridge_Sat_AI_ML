"""Tests for the ingestion service's /health endpoint."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_200_and_metadata() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "economicbridge-ingestion"
    assert "nasa_firms_configured" in body


def test_health_response_carries_trace_id_header() -> None:
    response = client.get("/api/v1/health")
    trace = response.headers.get("X-Trace-Id")
    assert trace is not None
    assert len(trace) > 0
