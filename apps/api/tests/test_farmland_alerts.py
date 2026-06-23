"""Integration tests for GET /api/v1/farmland/alerts.

Require:
  - Postgres reachable
  - Migrations up through 0003 applied (`alembic upgrade head`)
  - Seed data loaded (`python -m scripts.seed_farmland_alerts`)

Skipped by default. Run with: `pytest -m integration`.

Covered:
  - Missing X-Tenant-Id → 400
  - Unknown X-Tenant-Id → 404 (caught by middleware)
  - Happy path: kebbi returns the seeded fixtures
  - Pagination meta.total + page slicing
  - Severity filter
  - Status filter
  - Cross-tenant isolation (kebbi alerts not visible from zamfara header)
  - since/until ordering check
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


def _kebbi() -> dict[str, str]:
    return {"X-Tenant-Id": "kebbi"}


# ─── Tenant header behaviour ───────────────────────────────────────────────


def test_alerts_without_tenant_header_returns_400() -> None:
    response = client.get("/api/v1/farmland/alerts")
    assert response.status_code == 400, response.text
    assert "X-Tenant-Id" in response.text


def test_alerts_with_unknown_tenant_returns_404() -> None:
    response = client.get(
        "/api/v1/farmland/alerts", headers={"X-Tenant-Id": "atlantis"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TENANT_NOT_FOUND"


# ─── Happy path + envelope shape ───────────────────────────────────────────


def test_alerts_happy_path_returns_envelope() -> None:
    response = client.get("/api/v1/farmland/alerts", headers=_kebbi())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["success"] is True
    assert body["error"] is None
    assert "alerts" in body["data"]
    assert isinstance(body["data"]["alerts"], list)
    # Seeded fixtures place at least one Kebbi alert
    assert len(body["data"]["alerts"]) >= 1

    meta = body["meta"]
    assert meta["pagination"]["page"] == 1
    assert meta["pagination"]["per_page"] == 20
    assert meta["pagination"]["total"] >= 1
    assert meta["trace_id"]


def test_alert_response_fields_are_present() -> None:
    response = client.get("/api/v1/farmland/alerts", headers=_kebbi())
    first = response.json()["data"]["alerts"][0]
    # Every alert must carry these public fields
    for key in (
        "id", "tenant_id", "alert_type", "severity", "status",
        "zone_name", "lga", "location", "created_at", "updated_at",
    ):
        assert key in first, f"missing field: {key!r}"
    # location is {lon, lat} or null
    if first["location"] is not None:
        assert "lon" in first["location"] and "lat" in first["location"]


# ─── Fire-status (live NASA FIRMS monitoring indicator) ────────────────────


def test_fire_status_requires_tenant_header() -> None:
    response = client.get("/api/v1/farmland/fire-status")
    assert response.status_code == 400
    assert "X-Tenant-Id" in response.text


def test_fire_status_returns_monitoring_shape() -> None:
    response = client.get("/api/v1/farmland/fire-status", headers=_kebbi())
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # Counts are always present integers; last_scan_at may be null if FIRMS
    # has not run for this tenant yet. detections never negative.
    assert isinstance(data["detections_24h"], int)
    assert isinstance(data["detections_7d"], int)
    assert data["detections_24h"] >= 0
    assert data["detections_7d"] >= data["detections_24h"] or data["detections_7d"] >= 0
    assert "FIRMS" in data["source"]
    assert "last_scan_at" in data


# ─── Pagination ────────────────────────────────────────────────────────────


def test_pagination_per_page_slices_results() -> None:
    full = client.get("/api/v1/farmland/alerts", headers=_kebbi()).json()
    total = full["meta"]["pagination"]["total"]
    if total < 2:
        pytest.skip("seed fixture has fewer than 2 alerts for kebbi")

    page1 = client.get(
        "/api/v1/farmland/alerts?per_page=1&page=1", headers=_kebbi()
    ).json()
    page2 = client.get(
        "/api/v1/farmland/alerts?per_page=1&page=2", headers=_kebbi()
    ).json()

    assert len(page1["data"]["alerts"]) == 1
    assert len(page2["data"]["alerts"]) == 1
    assert page1["data"]["alerts"][0]["id"] != page2["data"]["alerts"][0]["id"]
    assert page1["meta"]["pagination"]["total"] == total


# ─── Filters ───────────────────────────────────────────────────────────────


def test_severity_filter_restricts_results() -> None:
    response = client.get(
        "/api/v1/farmland/alerts?severity=critical", headers=_kebbi()
    )
    assert response.status_code == 200
    for alert in response.json()["data"]["alerts"]:
        assert alert["severity"] == "critical"


def test_status_filter_restricts_results() -> None:
    response = client.get(
        "/api/v1/farmland/alerts?status=resolved", headers=_kebbi()
    )
    assert response.status_code == 200
    for alert in response.json()["data"]["alerts"]:
        assert alert["status"] == "resolved"


def test_since_after_until_returns_400() -> None:
    response = client.get(
        "/api/v1/farmland/alerts"
        "?since=2030-01-01T00:00:00Z&until=2020-01-01T00:00:00Z",
        headers=_kebbi(),
    )
    assert response.status_code == 400


# ─── Cross-tenant isolation ────────────────────────────────────────────────


def test_alerts_are_isolated_per_tenant() -> None:
    """Seed places Kebbi-specific zones in tenant_kebbi only; querying as
    zamfara must never return those same rows."""
    kebbi = client.get("/api/v1/farmland/alerts", headers=_kebbi()).json()
    zamfara = client.get(
        "/api/v1/farmland/alerts", headers={"X-Tenant-Id": "zamfara"}
    ).json()

    kebbi_ids = {a["id"] for a in kebbi["data"]["alerts"]}
    zamfara_ids = {a["id"] for a in zamfara["data"]["alerts"]}
    assert kebbi_ids.isdisjoint(zamfara_ids), \
        "alert IDs leaked across tenant schemas"

    # And every alert returned for a tenant claims that tenant in its payload
    for a in kebbi["data"]["alerts"]:
        assert a["tenant_id"] == "kebbi"
    for a in zamfara["data"]["alerts"]:
        assert a["tenant_id"] == "zamfara"
