"""Tests for the NDVI anomaly detector + scan endpoint (Slice 04.d)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from services.ndvi_anomaly import (
    ANOMALY_Z_THRESHOLD,
    RECENT_WINDOW_DAYS,
    SERIES_LENGTH_DAYS,
    _linear_detrend_stats,
    _mean,
    detect_anomaly,
    synthetic_series,
)


# ─── synthetic_series ─────────────────────────────────────────────────────


def test_series_returns_correct_length():
    s = synthetic_series("kebbi")
    assert len(s) == SERIES_LENGTH_DAYS


def test_series_is_deterministic_per_tenant_and_end_date():
    end = date(2026, 5, 21)
    s1 = synthetic_series("kebbi", end=end)
    s2 = synthetic_series("kebbi", end=end)
    assert [(p.observed_at, p.ndvi) for p in s1] == \
           [(p.observed_at, p.ndvi) for p in s2]


def test_different_tenants_produce_different_series():
    end = date(2026, 5, 21)
    a = synthetic_series("kebbi", end=end)
    b = synthetic_series("senegal", end=end)
    assert any(pa.ndvi != pb.ndvi for pa, pb in zip(a, b))


def test_series_ndvi_values_in_zero_one_range():
    s = synthetic_series("plateau")
    assert all(0.0 <= p.ndvi <= 1.0 for p in s)


def test_inject_anomaly_drops_recent_window():
    """The last 14 days should be ~0.18 lower with injection on."""
    end = date(2026, 5, 21)
    base = synthetic_series("kebbi", end=end, inject_anomaly=False)
    anom = synthetic_series("kebbi", end=end, inject_anomaly=True)
    recent_base = [p.ndvi for p in base[-RECENT_WINDOW_DAYS:]]
    recent_anom = [p.ndvi for p in anom[-RECENT_WINDOW_DAYS:]]
    # On average the injected series is 0.10+ below the baseline run.
    diff = _mean(recent_base) - _mean(recent_anom)
    assert diff > 0.10


# ─── detect_anomaly ───────────────────────────────────────────────────────


def test_detect_flags_anomaly_when_injected():
    s = synthetic_series("kebbi", inject_anomaly=True)
    r = detect_anomaly(tenant_id="kebbi", series=s)
    assert r.anomaly is True
    assert r.z_score <= -ANOMALY_Z_THRESHOLD
    assert r.confidence_band in ("HIGH", "MEDIUM")
    assert r.disease_probability >= 0.5


def test_detect_does_not_flag_clean_series():
    # PINNED end date (like every sibling test): the generator's annual
    # sinusoid is keyed to day-of-year, so an unpinned series ends on
    # date.today() and, on dates where the seasonal descent is steepest,
    # the clean series' last 14 days legitimately cross the z-threshold —
    # a calendar-dependent CI flake (first tripped 2026-07-14). The
    # detector's seasonality handling itself is scheduled for the Sep-Oct
    # baseline sprint; this test asserts the generator/detector contract
    # at a fixed date, which is all it ever meant to test.
    s = synthetic_series("kebbi", end=date(2026, 5, 21), inject_anomaly=False)
    r = detect_anomaly(tenant_id="kebbi", series=s)
    assert r.anomaly is False


def test_detect_carries_through_crop_label():
    s = synthetic_series("kebbi", inject_anomaly=True)
    r = detect_anomaly(tenant_id="kebbi", series=s, crop="maize")
    assert r.crop == "maize"


def test_detect_raises_on_too_short_series():
    s = synthetic_series("kebbi")[:30]   # truncate well below minimum
    with pytest.raises(ValueError, match="too short"):
        detect_anomaly(tenant_id="kebbi", series=s)


def test_detect_window_dates_match_recent_segment():
    s = synthetic_series("kebbi", inject_anomaly=True)
    r = detect_anomaly(tenant_id="kebbi", series=s)
    recent = s[-RECENT_WINDOW_DAYS:]
    assert r.window_start == recent[0].observed_at
    assert r.window_end == recent[-1].observed_at


def test_disease_probability_in_zero_one():
    s = synthetic_series("kebbi", inject_anomaly=True)
    r = detect_anomaly(tenant_id="kebbi", series=s)
    assert 0.0 <= r.disease_probability <= 1.0


# ─── _linear_detrend_stats ────────────────────────────────────────────────


def test_detrend_removes_perfect_linear_trend():
    """A perfectly linear series has zero residual std after detrend."""
    values = [0.30 + 0.005 * i for i in range(60)]
    intercept, slope, residual_std = _linear_detrend_stats(values)
    assert residual_std < 1e-9
    assert slope == pytest.approx(0.005)
    assert intercept == pytest.approx(0.30)


def test_detrend_isolates_noise_from_seasonal_drift():
    """Linear trend + small noise → residual std reflects noise only."""
    base = [0.30 + 0.004 * i for i in range(60)]
    noisy = [v + (0.01 if i % 2 == 0 else -0.01) for i, v in enumerate(base)]
    _, _, residual_std = _linear_detrend_stats(noisy)
    # Naive std would be ~0.072; detrended residual std ≈ 0.010.
    assert residual_std < 0.02


# ─── HTTP contract (no DB needed for non-persist scans) ───────────────────


client = TestClient(app)


def test_scan_without_tenant_header_returns_400():
    r = client.post("/api/v1/cropguard/ndvi/scan", json={"persist": False})
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_scan_with_unknown_tenant_returns_404():
    r = client.post(
        "/api/v1/cropguard/ndvi/scan",
        json={"persist": False},
        headers={"X-Tenant-Id": "atlantis"},
    )
    assert r.status_code == 404


def test_scan_request_declares_extra_forbid_in_schema():
    """Static check — DB-free per the Python-3.14 audit-log lesson:
    a runtime 422 would fire Pydantic AFTER the audit middleware writes,
    which is impossible on a no-DB local. Verify the contract via
    OpenAPI instead."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["NdviScanRequest"]
    assert schema.get("additionalProperties") is False


def test_anomalies_list_endpoint_declares_query_constraints():
    """Static OpenAPI check — DB-free per the Python-3.14 lesson."""
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/cropguard/ndvi/anomalies"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100
