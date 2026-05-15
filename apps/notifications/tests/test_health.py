"""Tests for the notifications-service /health endpoint."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_metadata() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "economicbridge-notifications"
    assert "termii_configured" in body
    assert "twilio_configured" in body


def test_health_response_carries_trace_id_header() -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Trace-Id")
