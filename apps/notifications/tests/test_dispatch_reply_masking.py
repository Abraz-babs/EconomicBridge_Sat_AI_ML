"""No dispatch reply may carry a full phone number.

Regression for the 2026-11-18 finding: `POST /notify/advisory` with
`dry_run: true` sends nothing and writes no outbox row, yet it returned every
matched subscriber's full number. Whoever held an organisation id with a signed
DPA could use it as a phone-number lookup. Both dispatch replies now mask to
the last four digits, the same as the outbox view.

The DPA gate, the session and the dispatcher are replaced with doubles, so
nothing here touches a database or sends an SMS.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import routers.notify as notify_router
from db import get_session
from dependencies import require_signed_dpa
from main import app
from services.dispatcher import DispatchOutcome

PHONES = ("+2348031234567", "+2348059876543")


def _outcomes(status: str) -> list[DispatchOutcome]:
    return [
        DispatchOutcome(
            subscriber_id=uuid4(), phone_e164=p, provider="termii", status=status,
            provider_message_id=None, error_message="body", language="en",
        )
        for p in PHONES
    ]


async def _no_session():
    yield None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    async def fake_advisory(*_a, **kw):
        return _outcomes("dry_run" if kw.get("dry_run") else "mock")

    async def fake_conflict(*_a, **_kw):
        return _outcomes("mock")

    monkeypatch.setattr(notify_router, "dispatch_farmer_advisory", fake_advisory)
    monkeypatch.setattr(notify_router, "dispatch_conflict_alert", fake_conflict)
    app.dependency_overrides[require_signed_dpa] = lambda: uuid4()
    app.dependency_overrides[get_session] = _no_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_signed_dpa, None)
        app.dependency_overrides.pop(get_session, None)


def _assert_masked(resp) -> None:
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]["dispatches"]
    assert len(rows) == len(PHONES)
    for row, phone in zip(rows, PHONES):
        assert "phone_e164" not in row
        assert row["phone_masked"] == "••••" + phone[-4:]
    for phone in PHONES:
        # Not even as a substring: the national part is the sensitive bit.
        assert phone not in resp.text
        assert phone[4:] not in resp.text


@pytest.mark.parametrize("dry_run", [True, False])
def test_advisory_reply_masks_every_number(client: TestClient, dry_run: bool) -> None:
    resp = client.post(
        "/api/v1/notify/advisory",
        json={"tenant_id": "kebbi", "advisory": "rainfall", "lga": "Argungu", "dry_run": dry_run},
        headers={"X-Tenant-Id": "kebbi"},
    )
    _assert_masked(resp)


def test_conflict_reply_masks_every_number(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/notify/conflict",
        json={"tenant_id": "kebbi", "severity": "critical", "alert_type": "conflict", "lga": "Argungu"},
        headers={"X-Tenant-Id": "kebbi"},
    )
    _assert_masked(resp)
