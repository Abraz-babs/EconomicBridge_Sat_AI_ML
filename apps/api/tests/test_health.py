"""Tests for GET /api/v1/health."""
from uuid import UUID

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_200_and_success_envelope() -> None:
    # Arrange / Act
    response = client.get("/api/v1/health")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "economicbridge-api"


def test_health_meta_contains_trace_id_and_timestamp() -> None:
    response = client.get("/api/v1/health")
    body = response.json()

    # trace_id must be a valid UUID
    UUID(body["meta"]["trace_id"])

    # timestamp must parse as an ISO-8601 datetime
    assert body["meta"]["timestamp"].endswith("Z") or "+" in body["meta"]["timestamp"]


def test_health_meta_tenant_id_is_null_for_public_endpoint() -> None:
    response = client.get("/api/v1/health")
    body = response.json()
    assert body["meta"]["tenant_id"] is None


def test_health_response_carries_trace_id_header() -> None:
    response = client.get("/api/v1/health")
    trace_header = response.headers.get("X-Trace-Id")
    assert trace_header is not None
    UUID(trace_header)


def test_health_response_carries_security_headers() -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_trace_id_changes_per_request() -> None:
    first = client.get("/api/v1/health").headers["X-Trace-Id"]
    second = client.get("/api/v1/health").headers["X-Trace-Id"]
    assert first != second
