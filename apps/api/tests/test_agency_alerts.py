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


def test_digest_gives_field_directions_for_real_points():
    """An agency dispatching a team needs a place, not just an LGA: a line
    with directions carries the village, ward and a maps link, and the GRID3
    credit appears once. A line without a point (crop health) has none."""
    from schemas.places import GeoPoint, NearestPlace
    from services.agency_alerts import directions

    place = NearestPlace(name="Mahuta", ward="Kyangakwai", distance_km=4.4,
                         direction="NE", location=GeoPoint(lon=3.78, lat=11.83))
    where = directions(place, 3.8097, 11.8606)
    assert where.startswith("4.4 km NE of Mahuta, Kyangakwai ward")
    assert "destination=11.86060,3.80970" in where

    lines = [
        AlertLine("medium", "Dandi", "radar land-surface change 1.1σ",
                  datetime(2026, 9, 24, tzinfo=timezone.utc), where),
        AlertLine("high", "Suru", "crop poor", datetime(2026, 9, 24, tzinfo=timezone.utc)),
    ]
    _subject, body = _render("Kebbi SEMA", "kebbi", "farmland", lines,
                             datetime(2026, 9, 23, tzinfo=timezone.utc))
    assert "      4.4 km NE of Mahuta" in body
    assert body.count("Village names: GRID3, CC BY 4.0.") == 1
    assert directions(None, 3.8, 11.8) is None
