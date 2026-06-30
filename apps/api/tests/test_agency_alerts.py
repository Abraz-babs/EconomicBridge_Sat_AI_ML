"""Tests for government-agency email alert digests. DB-free."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from main import app
from services.agency_alerts import AlertLine, _render


client = TestClient(app)


def test_render_digest_english_summary():
    lines = [
        AlertLine("critical", "Argungu", "flood - SAR drop", datetime(2026, 6, 30, tzinfo=timezone.utc)),
        AlertLine("high", "Birnin Kebbi", "drought - NDVI drop", datetime(2026, 6, 29, tzinfo=timezone.utc)),
    ]
    subject, body = _render("NEMA", "kebbi", "shockguard", lines,
                            datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert "2 new" in subject and "Kebbi" in subject
    assert body.startswith("Dear NEMA,")
    assert "CRITICAL" in body and "Argungu" in body
    assert "Bizra Farms" in body


def test_create_subscription_requires_super_admin():
    r = client.post(
        "/api/v1/admin/agency-alerts/subscriptions",
        json={"agency_name": "NEMA", "recipient_email": "a@b.gov.ng",
              "tenant_id": "kebbi", "module": "shockguard"},
    )
    assert r.status_code in (401, 403)


def test_list_subscriptions_requires_super_admin():
    assert client.get("/api/v1/admin/agency-alerts/subscriptions").status_code in (401, 403)


def test_send_requires_super_admin():
    assert client.post("/api/v1/admin/agency-alerts/send").status_code in (401, 403)


def test_subscription_module_is_constrained_in_schema():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["AgencySubIn"]["properties"]
    assert set(schema["module"]["enum"]) == {"farmland", "shockguard", "cropguard"}
