"""Tests for the CropGuard Farm Check records endpoints (save + recall).

DB-free by design (per the Python-3.14 audit-log lesson): the HTTP contract is
checked via TestClient + OpenAPI introspection, and the pure row<->payload
helpers are unit-tested directly. Real persistence is exercised by the
integration suite against a live schema.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from main import app
from routers.farm_check import _as_date, _iso_date, _row_to_record


client = TestClient(app)


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_save_without_tenant_header_returns_400():
    r = client.post(
        "/api/v1/cropguard/farm-checks",
        json={"lat": 9.07, "lon": 7.49, "crop": "maize", "health": "healthy"},
    )
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_list_without_tenant_header_returns_400():
    r = client.get("/api/v1/cropguard/farm-checks")
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_save_route_is_registered_and_created_status():
    spec = client.get("/api/openapi.json").json()
    post = spec["paths"]["/api/v1/cropguard/farm-checks"]["post"]
    assert "201" in post["responses"]


def test_delete_route_is_registered():
    spec = client.get("/api/openapi.json").json()
    assert "delete" in spec["paths"]["/api/v1/cropguard/farm-checks/{record_id}"]


def test_delete_without_tenant_header_returns_400():
    r = client.delete(
        "/api/v1/cropguard/farm-checks/00000000-0000-0000-0000-000000000000",
    )
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_list_route_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/cropguard/farm-checks"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100


def test_save_request_declares_coordinate_bounds():
    """Static OpenAPI check (DB-free): lat/lon are bounded so an out-of-range
    coordinate is rejected with 422 before any persistence runs."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["FarmCheckSaveRequest"]["properties"]
    assert schema["lat"]["minimum"] == -90 and schema["lat"]["maximum"] == 90
    assert schema["lon"]["minimum"] == -180 and schema["lon"]["maximum"] == 180


# ─── Date helpers ─────────────────────────────────────────────────────────


def test_as_date_parses_iso():
    assert _as_date("2026-06-25") == date(2026, 6, 25)


def test_as_date_tolerates_none_and_garbage():
    assert _as_date(None) is None
    assert _as_date("not-a-date") is None


def test_iso_date_roundtrips_date_and_datetime():
    assert _iso_date(date(2026, 6, 25)) == "2026-06-25"
    assert _iso_date(datetime(2026, 6, 25, 10, 30)) == "2026-06-25"
    assert _iso_date(None) is None


# ─── Row reconstruction (faithful recall) ─────────────────────────────────


def _sample_row() -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "kebbi",
        "lat": 9.07,
        "lon": 7.49,
        "crop": "maize",
        "lga": "Birnin Kebbi",
        "ndvi": 0.62,
        "ndvi_date": date(2026, 6, 25),
        "health": "moderate",
        "verdict": "Moderate vigour.",
        "sar_db": -8.4,
        "sar_date": date(2026, 6, 26),
        "stress_level": "none",
        "stress_z": 0.3,
        "stress_message": "No vegetation-stress signal.",
        "sample_count": 42,
        "area_ha": 5.76,
        "resolution_m": 11,
        "detail": {
            "trend": [{"date": "2026-05-23", "ndvi": 0.41},
                      {"date": "2026-06-25", "ndvi": 0.62}],
            "passes": [
                {"date": "2026-05-23", "ndvi": 0.41, "health": "stressed",
                 "verdict": "Stressed.", "sample_count": 30, "cloud_affected": False},
            ],
            "stress": {"level": "none", "z": 0.3,
                       "message": "No vegetation-stress signal."},
            "note": "Sentinel-2 latest usable pass.",
            "source": "copernicus_sentinel_v1",
        },
        "source": "copernicus_sentinel_v1",
        "note": "Sentinel-2 latest usable pass.",
        "created_at": datetime(2026, 6, 28, 9, 0, tzinfo=timezone.utc),
    }


def test_row_to_record_rebuilds_trend_passes_and_stress():
    rec = _row_to_record(_sample_row())
    assert rec.crop == "maize"
    assert rec.lga == "Birnin Kebbi"
    assert rec.ndvi == 0.62
    assert rec.ndvi_date == "2026-06-25"
    assert rec.sar_date == "2026-06-26"
    assert len(rec.trend) == 2
    assert len(rec.passes) == 1
    assert rec.passes[0].health == "stressed"
    assert rec.stress is not None
    assert rec.stress.level == "none"


def test_row_to_record_handles_missing_optionals():
    row = _sample_row()
    row.update({
        "lga": None, "ndvi": None, "ndvi_date": None,
        "sar_db": None, "sar_date": None, "detail": {},
    })
    rec = _row_to_record(row)
    assert rec.lga is None
    assert rec.ndvi is None
    assert rec.ndvi_date is None
    assert rec.trend == []
    assert rec.passes == []
    assert rec.stress is None
