"""Integration tests for TenantContext middleware + get_session search_path.

Require a live DB with migrations applied through 0002 (pilot tenant schemas).
Skipped by default. Run with: `pytest -m integration`.

Covered behaviours:
  - GET /tenant-info without X-Tenant-Id     → tenant_id is null, current_schema = public
  - GET /tenant-info with valid X-Tenant-Id  → tenant_id matches, current_schema = tenant_<id>
  - GET /tenant-info with invalid X-Tenant-Id → 404 TENANT_NOT_FOUND
  - Cross-tenant isolation: insert into tenant_kebbi.widgets, query under
    tenant_zamfara → returns 0 rows (the widgets table in zamfara's schema is
    a different physical table)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from config import get_settings
from main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


# ─── /tenant-info shape ────────────────────────────────────────────────────


def test_tenant_info_without_header_returns_public_schema() -> None:
    response = client.get("/api/v1/tenant-info")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["tenant_id"] is None
    # When no tenant is set the session uses the default search_path.
    assert "public" in body["data"]["db_search_path"]


def test_tenant_info_with_valid_header_switches_schema() -> None:
    response = client.get("/api/v1/tenant-info", headers={"X-Tenant-Id": "kebbi"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["tenant_id"] == "kebbi"
    assert body["data"]["db_current_schema"] == "tenant_kebbi"
    assert "tenant_kebbi" in body["data"]["db_search_path"]


def test_tenant_info_with_unknown_header_returns_404() -> None:
    response = client.get(
        "/api/v1/tenant-info",
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "TENANT_NOT_FOUND"


def test_tenant_id_is_normalized_to_lowercase() -> None:
    response = client.get("/api/v1/tenant-info", headers={"X-Tenant-Id": "KEBBI"})
    assert response.status_code == 200
    assert response.json()["data"]["tenant_id"] == "kebbi"


# ─── Cross-tenant isolation proof ──────────────────────────────────────────


def test_cross_tenant_widget_isolation() -> None:
    """Data inserted in tenant_kebbi.widgets must not be visible from tenant_zamfara."""
    # Use the sync URL (psycopg2) for the setup INSERT so we don't have to
    # spin up an async event loop in the test fixture.
    engine = create_engine(get_settings().database_url_sync, future=True)
    marker = f"isolation-probe-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(text("SET search_path TO tenant_kebbi, public"))
        conn.execute(text("INSERT INTO widgets (name) VALUES (:n)"), {"n": marker})

    try:
        # Read via the API as tenant_kebbi — must see the row.
        kebbi = client.get("/api/v1/tenant-info", headers={"X-Tenant-Id": "kebbi"})
        assert kebbi.status_code == 200
        assert kebbi.json()["data"]["db_current_schema"] == "tenant_kebbi"

        # Now query the widgets table directly under each tenant via raw SQL,
        # bypassing the API — confirms isolation is enforced at the schema layer.
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            visible_in_kebbi = conn.execute(
                text("SELECT COUNT(*) FROM widgets WHERE name = :n"), {"n": marker}
            ).scalar_one()
            assert visible_in_kebbi == 1, "marker should be visible in tenant_kebbi"

        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_zamfara, public"))
            visible_in_zamfara = conn.execute(
                text("SELECT COUNT(*) FROM widgets WHERE name = :n"), {"n": marker}
            ).scalar_one()
            assert visible_in_zamfara == 0, "marker MUST NOT leak into tenant_zamfara"
    finally:
        # Cleanup the marker
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            conn.execute(text("DELETE FROM widgets WHERE name = :n"), {"n": marker})
        engine.dispose()
