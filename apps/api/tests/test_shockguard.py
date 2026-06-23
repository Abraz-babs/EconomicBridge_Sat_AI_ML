"""Tests for ShockGuard flood + drought detectors + HTTP contract (Slice 05)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.shockguard import _event_row
from services.shock_detector import (
    DROUGHT_BASELINE_DAYS,
    DROUGHT_RECENT_DAYS,
    DROUGHT_SERIES_DAYS,
    DROUGHT_STRESS_THRESHOLD,
    FLOOD_BASELINE_DAYS,
    FLOOD_RECENT_DAYS,
    FLOOD_SERIES_DAYS,
    FLOOD_Z_THRESHOLD,
    TENANT_SHOCK_PROFILE,
    _linear_detrend_stats,
    _scale_from_z,
    detect_drought,
    detect_flood,
    synthetic_drought_series,
    synthetic_flood_series,
)


# ─── synthetic_flood_series ───────────────────────────────────────────────


def test_flood_series_returns_correct_length():
    s = synthetic_flood_series("kebbi")
    assert len(s) == FLOOD_SERIES_DAYS


def test_flood_series_is_deterministic_per_tenant_and_end_date():
    end = date(2026, 5, 21)
    a = synthetic_flood_series("benue", end=end)
    b = synthetic_flood_series("benue", end=end)
    assert [(p.observed_at, p.backscatter_db) for p in a] == \
           [(p.observed_at, p.backscatter_db) for p in b]


def test_flood_series_differs_across_tenants():
    end = date(2026, 5, 21)
    a = synthetic_flood_series("kebbi", end=end)
    b = synthetic_flood_series("benue", end=end)
    assert any(pa.backscatter_db != pb.backscatter_db for pa, pb in zip(a, b))


def test_flood_inject_drops_recent_backscatter():
    """Last FLOOD_RECENT_DAYS should average ≥ 2 dB below the un-injected run
    for tenants with flood_factor ≥ 0.6 (canonical water-over-land drop)."""
    end = date(2026, 5, 21)
    base = synthetic_flood_series("benue", end=end, inject_flood=False)
    flood = synthetic_flood_series("benue", end=end, inject_flood=True)
    base_recent = sum(p.backscatter_db for p in base[-FLOOD_RECENT_DAYS:]) / FLOOD_RECENT_DAYS
    flood_recent = sum(p.backscatter_db for p in flood[-FLOOD_RECENT_DAYS:]) / FLOOD_RECENT_DAYS
    assert base_recent - flood_recent > 2.0


# ─── detect_flood ─────────────────────────────────────────────────────────


def test_detect_flood_triggers_when_injected():
    """A 5 dB × flood_factor drop must push z below -FLOOD_Z_THRESHOLD."""
    s = synthetic_flood_series("benue", inject_flood=True)
    r = detect_flood(tenant_id="benue", series=s)
    assert r.triggered is True
    assert r.metrics["z_score"] <= -FLOOD_Z_THRESHOLD
    assert r.severity in ("medium", "high", "critical")
    assert r.event_type == "flood"
    assert r.affected_area_km2 > 0
    assert r.population_at_risk > 0


def test_detect_flood_quiet_series_does_not_trigger():
    s = synthetic_flood_series("benue", inject_flood=False)
    r = detect_flood(tenant_id="benue", series=s)
    assert r.triggered is False
    assert r.affected_area_km2 == 0.0
    assert r.population_at_risk == 0


def test_detect_flood_raises_on_too_short_series():
    s = synthetic_flood_series("kebbi")[:FLOOD_BASELINE_DAYS]  # below minimum
    with pytest.raises(ValueError, match="too short"):
        detect_flood(tenant_id="kebbi", series=s)


def test_detect_flood_carries_detector_identity():
    s = synthetic_flood_series("benue", inject_flood=True)
    r = detect_flood(tenant_id="benue", series=s)
    assert r.detector_name == "shock_flood_v1"
    assert r.detector_version.startswith("0.")


# ─── detect_drought ───────────────────────────────────────────────────────


def test_detect_drought_triggers_when_injected():
    """Sustained heat + NDVI collapse should lift recent stress over the
    DROUGHT_STRESS_THRESHOLD for drought-prone tenants."""
    s = synthetic_drought_series("kebbi", inject_drought=True)
    r = detect_drought(tenant_id="kebbi", series=s)
    assert r.triggered is True
    assert r.metrics["recent_stress_mean"] >= DROUGHT_STRESS_THRESHOLD
    assert r.event_type == "drought"
    assert r.severity in ("low", "medium", "high", "critical")
    assert r.population_at_risk > 0


def test_detect_drought_quiet_series_does_not_trigger():
    s = synthetic_drought_series("kebbi", inject_drought=False)
    r = detect_drought(tenant_id="kebbi", series=s)
    assert r.triggered is False
    assert r.severity == "low"
    assert r.affected_area_km2 == 0.0


def test_detect_drought_raises_on_too_short_series():
    s = synthetic_drought_series("kebbi")[:DROUGHT_BASELINE_DAYS]  # below minimum
    with pytest.raises(ValueError, match="too short"):
        detect_drought(tenant_id="kebbi", series=s)


def test_detect_drought_carries_detector_identity():
    s = synthetic_drought_series("kebbi", inject_drought=True)
    r = detect_drought(tenant_id="kebbi", series=s)
    assert r.detector_name == "shock_drought_v1"


def test_drought_series_length_matches_window():
    s = synthetic_drought_series("kebbi")
    assert len(s) == DROUGHT_SERIES_DAYS
    assert DROUGHT_SERIES_DAYS >= DROUGHT_BASELINE_DAYS + DROUGHT_RECENT_DAYS


# ─── Tenant profile sanity ────────────────────────────────────────────────


def test_tenant_profiles_cover_all_pilots():
    """All 10 pilots in tenants.yaml have a shock profile so detectors
    don't silently fall back to the default tuple in production."""
    expected = {
        "kebbi", "benue", "plateau", "kaduna", "niger",
        "zamfara", "nasarawa", "fct", "ghana", "senegal",
    }
    assert expected <= set(TENANT_SHOCK_PROFILE.keys())


def test_tenant_profile_risk_factors_in_unit_range():
    for tenant, profile in TENANT_SHOCK_PROFILE.items():
        flood_factor, drought_factor = profile[3], profile[4]
        assert 0.0 < flood_factor <= 1.5, f"{tenant} flood_factor {flood_factor}"
        assert 0.0 < drought_factor <= 1.5, f"{tenant} drought_factor {drought_factor}"


# ─── _linear_detrend_stats ────────────────────────────────────────────────


def test_detrend_removes_perfect_linear_trend():
    values = [-12.0 + 0.02 * i for i in range(60)]
    intercept, slope, residual_std = _linear_detrend_stats(values)
    assert residual_std < 1e-9
    assert slope == pytest.approx(0.02)
    assert intercept == pytest.approx(-12.0)


def test_detrend_short_series_returns_zero_std():
    intercept, slope, residual_std = _linear_detrend_stats([-11.5])
    assert residual_std == 0.0
    assert slope == 0.0


# ─── _scale_from_z severity bands ─────────────────────────────────────────


def test_scale_from_z_critical_band():
    sev, band, conf = _scale_from_z(-4.0)
    assert sev == "critical"
    assert band == "HIGH"
    assert conf >= 0.85


def test_scale_from_z_high_band():
    sev, band, _ = _scale_from_z(-2.8)
    assert sev == "high"
    assert band == "HIGH"


def test_scale_from_z_medium_band():
    sev, band, _ = _scale_from_z(-2.1)
    assert sev == "medium"
    assert band == "MEDIUM"


def test_scale_from_z_low_band_for_quiet_series():
    sev, band, _ = _scale_from_z(0.3)
    assert sev == "low"
    assert band == "LOW"


# ─── HTTP contract (DB-free per the Python-3.14 audit-log lesson) ─────────


client = TestClient(app)


def test_scan_without_tenant_header_returns_400():
    r = client.post("/api/v1/shockguard/scan", json={"event_type": "flood"})
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_scan_with_unknown_tenant_returns_404():
    r = client.post(
        "/api/v1/shockguard/scan",
        json={"event_type": "flood", "persist": False},
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert r.status_code == 404


def test_events_without_tenant_header_returns_400():
    r = client.get("/api/v1/shockguard/events")
    assert r.status_code == 400


def test_scan_request_declares_extra_forbid_in_schema():
    """Static OpenAPI check — a runtime 422 would fire Pydantic AFTER
    audit middleware writes, which can't happen on a no-DB local."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ShockScanRequest"]
    assert schema.get("additionalProperties") is False


def test_scan_request_event_type_enum_locked_to_flood_drought():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ShockScanRequest"]
    event_type_schema = schema["properties"]["event_type"]
    # Pydantic emits Literal as either an enum on the property or a $ref.
    if "$ref" in event_type_schema:
        ref = event_type_schema["$ref"].split("/")[-1]
        enum = spec["components"]["schemas"][ref]["enum"]
    else:
        enum = event_type_schema.get("enum", [])
    assert set(enum) == {"flood", "drought"}


def test_events_endpoint_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/shockguard/events"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100


def test_events_response_declares_monitoring_status_fields():
    """The events response carries last_scan_at + active_shock_count so the
    panel can show 'scanned today, all clear' instead of looking stale."""
    spec = client.get("/api/openapi.json").json()
    props = spec["components"]["schemas"]["ShockEventListData"]["properties"]
    assert "last_scan_at" in props
    assert "active_shock_count" in props


# ─── _event_row location mapping (DB-free row → ShockEventRow) ─────────────


def _base_event_row() -> dict:
    return {
        "id": uuid4(),
        "tenant_id": "kebbi",
        "event_type": "flood",
        "detector_name": "shock_flood_v1",
        "detector_version": "0.1.0-statistical",
        "severity": "critical",
        "confidence": 0.93,
        "confidence_band": "HIGH",
        "requires_human_review": False,
        "projected_onset_hours": 24,
        "affected_area_km2": 278.0,
        "population_at_risk": 32664,
        "lga": "Argungu",
        "zone_name": "Argungu",
        "metrics": {"backscatter_delta_db": -5.5},
        "source": "seed_v1",
        "created_at": datetime.now(timezone.utc),
    }


def test_event_row_attaches_real_location():
    """ST_X/ST_Y(location) → a LonLat the map uses for the marker."""
    row = _base_event_row() | {"lon": 4.52, "lat": 12.74}
    event = _event_row(row)
    assert event.location is not None
    assert (event.location.lon, event.location.lat) == (4.52, 12.74)
    assert event.lga == "Argungu"


def test_event_row_location_none_when_geometry_missing():
    """A NULL geometry (lon/lat NULL) yields location=None so the map
    falls back to a synthetic position instead of crashing."""
    row = _base_event_row() | {"lon": None, "lat": None}
    event = _event_row(row)
    assert event.location is None
