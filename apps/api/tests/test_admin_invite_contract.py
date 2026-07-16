"""Contract tests for the tenant-invite endpoint (DB-free, via OpenAPI).

The 2026-07-16 lesson: re-inviting an already-ACTIVE account minted no
token and sent no email, but returned 200 — the admin reasonably believed
invites were broken. The endpoint now declares (and raises) an explicit
409 for that case; this pins the contract.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_invite_route_declares_already_active_conflict():
    spec = client.get("/api/openapi.json").json()
    post = spec["paths"]["/api/v1/admin/tenants/{tenant_id}/invite"]["post"]
    assert "409" in post["responses"]
    assert "ACTIVE" in post["responses"]["409"]["description"]


def test_invite_route_requires_auth():
    r = client.post(
        "/api/v1/admin/tenants/kebbi/invite",
        json={"admin_email": "someone@example.org", "admin_name": None},
    )
    # Without a super-admin bearer token the route must refuse.
    assert r.status_code in (401, 403)
