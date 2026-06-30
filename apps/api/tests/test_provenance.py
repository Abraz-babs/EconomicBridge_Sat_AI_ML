"""Tests for GET /api/v1/provenance (the data-source catalog). DB-free."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_provenance_returns_catalog_and_budget():
    r = client.get("/api/v1/provenance")
    assert r.status_code == 200
    body = r.json()
    data = body["data"]
    assert len(data["feeds"]) >= 6
    modules = {f["module"] for f in data["feeds"]}
    assert {"Farmland Protection", "Economic Visibility", "CropGuard"} <= modules
    assert data["compute"]["monthly_pu"] == 30000
    assert "attribution" in data["feeds"][0]


def test_every_feed_declares_license_and_attribution():
    data = client.get("/api/v1/provenance").json()["data"]
    for f in data["feeds"]:
        assert f["license"] and f["attribution"] and f["satellites"]
        assert f["kind"] in ("live", "modelled", "derived")


def test_farmland_feed_names_real_satellites():
    data = client.get("/api/v1/provenance").json()["data"]
    farm = next(f for f in data["feeds"] if f["module"] == "Farmland Protection")
    assert any("Sentinel-1" in s for s in farm["satellites"])
    assert farm["kind"] == "live"
