"""Tests for the Slice 17 DPA gate on notifications routes.

GET /api/v1/subscribers + POST /api/v1/notify/conflict carry the
same `Depends(require_signed_dpa)` Slice 14 introduced on the API
side. This file mirrors apps/api/tests/test_dpa_enforcement.py — all
short-circuits exercised without a DB connection (CI runs without
Postgres) by inspecting FastAPI's route dependency tree for the
"is this route gated" assertion.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ─── Header short-circuits (no DB touched) ─────────────────────────────────


def test_subscribers_list_without_any_headers_returns_403_tenant_required():
    r = client.get("/api/v1/subscribers")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "TENANT_REQUIRED"


def test_subscribers_list_with_tenant_but_no_org_returns_403_dpa_required():
    r = client.get(
        "/api/v1/subscribers",
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "DPA_REQUIRED"


def test_subscribers_list_with_invalid_org_uuid_returns_403_dpa_required():
    r = client.get(
        "/api/v1/subscribers",
        headers={
            "X-Tenant-Id": "kebbi",
            "X-Organisation-Id": "not-a-uuid",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "DPA_REQUIRED"
    assert "UUID" in r.json()["error"]["message"]


def test_subscribers_list_with_unknown_tenant_returns_403_tenant_required():
    r = client.get(
        "/api/v1/subscribers",
        headers={
            "X-Tenant-Id": "atlantis",
            "X-Organisation-Id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "TENANT_REQUIRED"


def test_notify_conflict_without_headers_returns_403_tenant_required():
    r = client.post(
        "/api/v1/notify/conflict",
        json={
            "tenant_id": "kebbi",
            "alert_type": "conflict",
            "severity": "high",
            "zone_name": "Kebbi · Maru border zone",
            "predicted_breach_hours": 36,
            "confidence": 0.88,
            "lat": 12.7,
            "lon": 4.5,
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "TENANT_REQUIRED"


# ─── Dependency-tree contract (no HTTP request) ────────────────────────────


def test_gated_and_open_routes_have_the_expected_deps():
    """Confirm via app.routes which notifications routes are gated and
    which intentionally remain open."""
    from dependencies import require_signed_dpa

    def has_dep(dependant, target) -> bool:
        if dependant.call is target:
            return True
        return any(has_dep(sub, target) for sub in dependant.dependencies)

    routes = {
        (r.path, m): r
        for r in app.routes
        if hasattr(r, "methods")
        for m in r.methods
    }

    get_subs = routes[("/api/v1/subscribers", "GET")]
    post_subs = routes[("/api/v1/subscribers", "POST")]
    notify = routes[("/api/v1/notify/conflict", "POST")]
    health = routes[("/api/v1/health", "GET")]

    # Gated — Slice 17.
    assert has_dep(get_subs.dependant, require_signed_dpa), (
        "GET /subscribers must be DPA-gated — returns subscriber phone "
        "numbers in E.164."
    )
    assert has_dep(notify.dependant, require_signed_dpa), (
        "POST /notify/conflict must be DPA-gated — dispatches real SMS."
    )

    # Intentionally open — consistent with Slice 14's POST-open pattern
    # so subjects can opt themselves in via partner agencies.
    assert not has_dep(post_subs.dependant, require_signed_dpa), (
        "POST /subscribers must remain open so subjects can opt in "
        "without organisational affiliation (Slice 14 convention)."
    )
    assert not has_dep(health.dependant, require_signed_dpa), (
        "Health checks are open."
    )


# ─── OpenAPI documents the gate ────────────────────────────────────────────


def test_openapi_advertises_dpa_gate_on_gated_routes():
    spec = client.get("/api/openapi.json").json()
    get_subs_desc = spec["paths"]["/api/v1/subscribers"]["get"].get("description", "")
    notify_desc = spec["paths"]["/api/v1/notify/conflict"]["post"].get("description", "")
    for desc in (get_subs_desc, notify_desc):
        assert "DPA" in desc or "Data Processing Agreement" in desc, (
            "Partner integrators need to see the gate requirement in /openapi.json"
        )
