"""An account may only reach the tenants it was registered for.

This is the real client boundary — not the UI's tenant selector, which only
decides what is offered. A registered state account holds
`permitted_tenants = [its own state]`, so presenting any other X-Tenant-Id must
be refused even with a perfectly valid token; a partner account (NASRDA and
similar) holds every pilot and may switch between them; super-admin is
unrestricted so support can reproduce a complaint.

The check lives in TenantContextMiddleware and had no test, which is why this
file exists — the enforcement is one `if`, and a refactor that drops it would
otherwise be invisible until a customer read another customer's data.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from core.security import create_access_token
from middleware.tenant import TenantContextMiddleware
from services.tenants import PILOT_TENANT_IDS


def _client() -> TestClient:
    """A stub app behind the real middleware.

    The middleware touches no database, so testing it directly keeps these
    assertions about the access rule rather than about whatever the farmland
    handler happens to return.
    """
    async def ok(request):
        return PlainTextResponse(str(getattr(request.state, "tenant_id", None)))

    app = Starlette(routes=[Route("/api/v1/farmland/alerts", ok)])
    app.add_middleware(TenantContextMiddleware)
    return TestClient(app)


def _headers(role: str, tenants: list[str], target: str) -> dict[str, str]:
    token = create_access_token(
        user_id=uuid4(), role=role, org_id=uuid4(), permitted_tenants=tenants,
    )
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": target}


def _other_pilot(not_this: str) -> str:
    return next(t for t in PILOT_TENANT_IDS if t != not_this)


def test_state_account_cannot_read_another_state():
    """The case that matters: a valid token is not a licence for any tenant."""
    client = _client()
    target = _other_pilot("kebbi")

    r = client.get("/api/v1/farmland/alerts",
                   headers=_headers("tenant_admin", ["kebbi"], target))

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "TENANT_FORBIDDEN"


def test_state_account_can_read_its_own_state():
    client = _client()

    r = client.get("/api/v1/farmland/alerts",
                   headers=_headers("tenant_admin", ["kebbi"], "kebbi"))

    assert r.status_code == 200
    assert r.text == "kebbi"


def test_partner_account_may_switch_between_the_pilots_it_holds():
    """NASRDA-style: geographic=False onboarding grants every pilot."""
    client = _client()
    permitted = list(PILOT_TENANT_IDS)

    for target in permitted[:3]:
        r = client.get("/api/v1/farmland/alerts",
                       headers=_headers("tenant_admin", permitted, target))
        assert r.status_code == 200, target


def test_super_admin_reaches_any_tenant_holding_none():
    """How support reproduces a complaint — permitted_tenants is empty and it
    still passes, because the exemption is on role, not on the list."""
    client = _client()

    r = client.get("/api/v1/farmland/alerts",
                   headers=_headers("super_admin", [], _other_pilot("kebbi")))

    assert r.status_code == 200


def test_anonymous_is_not_tenant_scoped():
    """The public overview is open by design and carries no account."""
    client = _client()

    r = client.get("/api/v1/farmland/alerts", headers={"X-Tenant-Id": "kebbi"})

    assert r.status_code == 200


def test_unknown_tenant_is_404_not_403():
    """Distinguishable on purpose: 404 leaks nothing about who may read what."""
    client = _client()

    r = client.get("/api/v1/farmland/alerts",
                   headers=_headers("tenant_admin", ["kebbi"], "atlantis"))

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TENANT_NOT_FOUND"
