"""Tests for POST /api/v1/notify/conflict + GET/POST /api/v1/subscribers.

The validation paths (400 / 404 / 422) don't need a database. The full
round-trip (subscriber INSERT → matching → mock dispatch → outbox UPDATE)
runs only under `pytest -m integration` against a live DB.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _payload(**overrides) -> dict:
    body = {
        "tenant_id": "kebbi",
        "severity": "critical",
        "alert_type": "conflict",
        "lga": "Argungu",
        "affected_area_ha": 82.0,
        "livelihoods_at_risk": 412,
        "eta_hours": 6,
    }
    body.update(overrides)
    return body


# NOTE (Slice 17): /notify/conflict and GET /subscribers are now DPA-gated.
# The dependency runs BEFORE Pydantic body validation + the route's own
# tenant lookup, so the old expectations (404 / 422 / 400) no longer fire
# for unauthenticated callers. Coverage for the gate itself lives in
# tests/test_dpa_enforcement.py.


def test_notify_unknown_tenant_returns_403_via_gate() -> None:
    """Body tenant_id='atlantis' would have 404'd pre-Slice-17. Now the
    gate fires first (missing X-Tenant-Id → TENANT_REQUIRED)."""
    response = client.post("/api/v1/notify/conflict", json=_payload(tenant_id="atlantis"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_REQUIRED"


def test_notify_invalid_severity_blocked_by_gate_before_pydantic() -> None:
    """Pydantic body validation only runs after the gate clears. With
    no DPA headers we never reach the severity check — gate 403s first."""
    response = client.post("/api/v1/notify/conflict", json=_payload(severity="catastrophic"))
    assert response.status_code == 403


def test_notify_invalid_alert_type_blocked_by_gate_before_pydantic() -> None:
    response = client.post("/api/v1/notify/conflict", json=_payload(alert_type="zombie"))
    assert response.status_code == 403


def test_subscribers_missing_tenant_header_returns_403_via_gate() -> None:
    """GET /subscribers used to 400 on missing X-Tenant-Id. Now the DPA
    gate raises TENANT_REQUIRED with the same intent (no tenant context)."""
    response = client.get("/api/v1/subscribers")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_REQUIRED"


def test_subscribers_unknown_tenant_header_returns_403_via_gate() -> None:
    response = client.get("/api/v1/subscribers", headers={"X-Tenant-Id": "atlantis"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_REQUIRED"


def test_create_subscriber_rejects_invalid_e164() -> None:
    response = client.post(
        "/api/v1/subscribers",
        json={"phone_e164": "07012345678", "lga": "Argungu"},
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert response.status_code == 422
    assert "phone_e164" in response.text


def test_create_subscriber_rejects_unknown_field() -> None:
    response = client.post(
        "/api/v1/subscribers",
        json={"phone_e164": "+2348012345678", "mystery": "x"},
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert response.status_code == 422


# ─── Integration: full round-trip (DB required) ──────────────────────────


@pytest.mark.integration
def test_full_dispatch_round_trip_uses_mock_gateway() -> None:
    """Create a subscriber → fire /notify/conflict → see mock dispatch."""
    headers = {"X-Tenant-Id": "kebbi"}

    # Clean any prior test subscribers
    from sqlalchemy import create_engine, text
    from config import get_settings
    sync_url = get_settings().database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    )
    engine = create_engine(sync_url, future=True)
    test_phone = "+2348099887766"
    try:
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            conn.execute(
                text("DELETE FROM alert_subscribers WHERE phone_e164 = :p"),
                {"p": test_phone},
            )

        # Create the subscriber
        resp = client.post(
            "/api/v1/subscribers",
            json={
                "full_name": "Test Farmer",
                "phone_e164": test_phone,
                "language": "en",
                "lga": "Argungu",
                "severity_threshold": "high",
                "alert_types": ["conflict"],
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        subscriber_id = resp.json()["data"]["id"]

        # Trigger the dispatch
        resp = client.post(
            "/api/v1/notify/conflict",
            json={
                "tenant_id": "kebbi",
                "severity": "critical",
                "alert_type": "conflict",
                "lga": "Argungu",
                "affected_area_ha": 82.0,
                "livelihoods_at_risk": 412,
                "eta_hours": 6,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["matched_subscribers"] >= 1
        assert body["dispatched"] >= 1
        assert body["provider_chosen"] == "termii"  # kebbi → termii (mock-fallback in dev)
        # Find our test subscriber's outcome
        ours = [d for d in body["dispatches"] if d["subscriber_id"] == subscriber_id]
        assert len(ours) == 1
        assert ours[0]["status"] in {"sent", "mock"}
        assert ours[0]["phone_e164"] == test_phone

        # Verify the outbox row landed
        with engine.begin() as conn:
            cnt = conn.execute(
                text(
                    "SELECT COUNT(*) FROM public.sms_outbox "
                    "WHERE phone_e164 = :p AND tenant_id = 'kebbi'"
                ),
                {"p": test_phone},
            ).scalar_one()
            assert int(cnt) >= 1
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM public.sms_outbox WHERE phone_e164 = :p"),
                {"p": test_phone},
            )
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            conn.execute(
                text("DELETE FROM alert_subscribers WHERE phone_e164 = :p"),
                {"p": test_phone},
            )
        engine.dispose()
