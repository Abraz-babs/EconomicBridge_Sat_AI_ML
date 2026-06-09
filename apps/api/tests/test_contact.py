"""Tests for the public contact-form endpoint (POST /api/v1/contact)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import routers.contact as contact_mod
from main import app

client = TestClient(app)

VALID = {
    "name": "Amina B.",
    "organisation": "Kebbi Agric Dept",
    "email": "amina@kebbi.gov.ng",
    "interest": "Farmland Protection pilot",
    "region": "Kebbi",
    "message": "We want to monitor encroachment.",
}


def _post(body: dict, ip: str):
    # X-Forwarded-For sets the rate-limit key, so each test isolates on its own IP.
    return client.post("/api/v1/contact", json=body, headers={"x-forwarded-for": ip})


def test_valid_inquiry_accepted():
    r = _post(VALID, "10.0.0.1")
    assert r.status_code == 200
    assert r.json()["data"]["received"] is True


def test_bad_email_rejected():
    r = _post({**VALID, "email": "notanemail"}, "10.0.0.2")
    assert r.status_code == 422


def test_missing_required_fields_rejected():
    r = _post({"email": "a@b.co", "interest": "X"}, "10.0.0.3")
    assert r.status_code == 422


def test_honeypot_is_silently_dropped(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        contact_mod, "send_contact_inquiry", lambda **kw: sent.append(kw),
    )
    r = _post({**VALID, "company_website": "http://spam.example"}, "10.0.0.4")
    assert r.status_code == 200          # bot sees success
    assert sent == []                    # but nothing is emailed


def test_real_inquiry_triggers_send(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        contact_mod, "send_contact_inquiry", lambda **kw: sent.append(kw),
    )
    r = _post(VALID, "10.0.0.5")
    assert r.status_code == 200
    assert len(sent) == 1
    assert sent[0]["email"] == "amina@kebbi.gov.ng"


def test_rate_limited_after_cap(monkeypatch):
    monkeypatch.setattr(contact_mod, "send_contact_inquiry", lambda **kw: None)
    ip = "10.9.9.9"
    for _ in range(contact_mod._MAX_PER_WINDOW):
        assert _post(VALID, ip).status_code == 200
    assert _post(VALID, ip).status_code == 429
