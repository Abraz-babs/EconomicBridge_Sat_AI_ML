"""Unit tests for per-account activity counting (services/activity.py).

Covers the buffer semantics the flusher depends on — no DB here; the flush
path is exercised in the integration tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from core.security import create_access_token
from middleware.activity import ActivityMiddleware
from services import activity


@pytest.fixture(autouse=True)
def _clean_buffer():
    activity._buffer.clear()
    activity._dropped = 0
    yield
    activity._buffer.clear()
    activity._dropped = 0


def _only_entry() -> tuple[int, datetime]:
    assert len(activity._buffer) == 1
    return next(iter(activity._buffer.values()))


def test_record_accumulates_into_one_key():
    # Arrange
    args = dict(user_id="u1", org_id="o1", tenant_id="kebbi", module="farmland")

    # Act
    for _ in range(3):
        activity.record(**args)

    # Assert
    count, _ = _only_entry()
    assert count == 3


def test_different_tenant_or_module_are_separate_keys():
    activity.record(user_id="u1", org_id="o1", tenant_id="kebbi", module="farmland")
    activity.record(user_id="u1", org_id="o1", tenant_id="niger", module="farmland")
    activity.record(user_id="u1", org_id="o1", tenant_id="kebbi", module="cropguard")

    assert len(activity._buffer) == 3


def test_missing_tenant_and_module_normalise_to_empty_string_not_none():
    """NULL would break ON CONFLICT — the PK columns must never be None.

    A composite primary key containing NULL never matches itself in Postgres,
    so the UPSERT would insert a duplicate row on every flush instead of
    incrementing. Guarding at the source is cheaper than a partial index.
    """
    activity.record(user_id="u1", org_id=None, tenant_id=None, module=None)

    (_, org_id, _, tenant_id, module) = next(iter(activity._buffer))
    assert org_id is None          # nullable column, fine
    assert tenant_id == ""         # PK column, must not be None
    assert module == ""


def test_buffer_ceiling_drops_new_keys_but_keeps_counting_existing():
    activity.record(user_id="held", org_id=None, tenant_id="t", module="m")
    original = dict(activity._buffer)
    activity._buffer.update(
        {(f"u{i}", None, datetime.now(timezone.utc).date(), "t", "m"): (1, datetime.now(timezone.utc))
         for i in range(activity.MAX_BUFFER_KEYS)}
    )

    # A brand-new key is dropped...
    activity.record(user_id="new", org_id=None, tenant_id="t", module="m")
    assert not any(k[0] == "new" for k in activity._buffer)
    assert activity._dropped == 1

    # ...but an existing one still increments, so an active account's numbers
    # stay truthful even while the buffer is saturated.
    activity.record(user_id="held", org_id=None, tenant_id="t", module="m")
    key = next(iter(original))
    assert activity._buffer[key][0] == 2


def test_flush_returns_zero_and_keeps_buffer_empty_when_nothing_recorded():
    assert asyncio.run(activity.flush()) == 0
    assert activity._buffer == {}


def test_failed_flush_returns_counts_to_the_buffer(monkeypatch):
    """A DB outage must not silently erase usage that was already counted."""
    activity.record(user_id="u1", org_id="o1", tenant_id="kebbi", module="farmland")
    activity.record(user_id="u1", org_id="o1", tenant_id="kebbi", module="farmland")

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("db.engine.get_session_factory", _boom)

    assert asyncio.run(activity.flush()) == 0
    count, _ = _only_entry()
    assert count == 2


# ─── ActivityMiddleware: what gets counted, and against whom ─────────────
#
# Exercised against a stub ASGI app rather than the real one. What is under
# test is the middleware's decision to count, which happens before any handler
# runs — routing through a DB-backed endpoint would add a database to a test
# that does not need one.


@pytest.fixture
def stub_client() -> TestClient:
    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/{path:path}", ok)])
    app.add_middleware(ActivityMiddleware)
    return TestClient(app)


def _bearer(user_id: UUID, role: str = "tenant_admin") -> dict[str, str]:
    token = create_access_token(
        user_id=user_id, role=role, org_id=uuid4(), permitted_tenants=["kebbi"],
    )
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_request_is_counted_against_its_account(stub_client):
    user_id = uuid4()

    stub_client.get("/api/v1/farmland/alerts",
                    headers={**_bearer(user_id), "X-Tenant-Id": "kebbi"})

    keys = list(activity._buffer)
    assert len(keys) == 1
    counted_user, _org, _day, tenant_id, module = keys[0]
    assert counted_user == str(user_id)
    assert tenant_id == "kebbi"
    assert module == "farmland"


def test_anonymous_traffic_is_not_counted(stub_client):
    """The public overview is open by design — no account to attribute it to."""
    stub_client.get("/api/v1/overview/summary")

    assert activity._buffer == {}


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/api/v1/health/db", "/api/docs", "/api/openapi.json",
     "/api/v1/auth/refresh", "/api/v1/auth/me", "/api/v1/auth/my-modules"],
)
def test_machinery_paths_are_not_counted(stub_client, path):
    """Load-balancer polls and dashboard housekeeping are not usage.

    These are real registered routes — a prefix typo here fails silently by
    counting the very traffic it was meant to exclude, so each one is pinned.
    """
    stub_client.get(path, headers=_bearer(uuid4()))

    assert activity._buffer == {}


def test_invalid_token_is_not_counted(stub_client):
    stub_client.get("/api/v1/farmland/alerts",
                    headers={"Authorization": "Bearer not-a-real-token",
                             "X-Tenant-Id": "kebbi"})

    assert activity._buffer == {}


def test_request_without_a_tenant_header_still_counts_the_account(stub_client):
    """Cross-tenant screens (the overview, reports) carry no X-Tenant-Id —
    they are still usage, just not attributable to one tenant."""
    user_id = uuid4()

    stub_client.get("/api/v1/reports/history", headers=_bearer(user_id))

    (counted_user, _org, _day, tenant_id, module) = next(iter(activity._buffer))
    assert counted_user == str(user_id)
    assert tenant_id == ""
    assert module == ""
