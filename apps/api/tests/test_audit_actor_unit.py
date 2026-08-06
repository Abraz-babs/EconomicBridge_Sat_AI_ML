"""The audit log must record WHO, not just what (CLAUDE.md §4.6).

`audit_log` has carried `actor_user_id` / `actor_org_id` since migration 0001,
but nothing populated them, so every historical row answers "who did this?"
with NULL. These tests pin the extraction.

They matter more than they look: the audit insert is deliberately fail-soft, so
a mistake in this path (a missing import, a renamed claim) does not raise — it
silently stops the audit log recording anything at all.
"""
from __future__ import annotations

from uuid import uuid4

from starlette.datastructures import Headers
from starlette.requests import Request

from core.security import create_access_token
from middleware.audit import _actor


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = Headers(headers or {}).raw
    return Request({"type": "http", "method": "POST", "path": "/api/v1/x",
                    "headers": raw})


def test_actor_is_extracted_from_the_bearer_token():
    user_id, org_id = uuid4(), uuid4()
    token = create_access_token(
        user_id=user_id, role="tenant_admin", org_id=org_id,
        permitted_tenants=["kebbi"],
    )

    assert _actor(_request({"Authorization": f"Bearer {token}"})) == (
        str(user_id), str(org_id),
    )


def test_anonymous_request_has_no_actor():
    """The public overview is unauthenticated by design — not an error."""
    assert _actor(_request()) == (None, None)


def test_invalid_token_has_no_actor_and_does_not_raise():
    assert _actor(_request({"Authorization": "Bearer garbage"})) == (None, None)


def test_non_bearer_scheme_has_no_actor():
    assert _actor(_request({"Authorization": "Basic dXNlcjpwYXNz"})) == (None, None)
