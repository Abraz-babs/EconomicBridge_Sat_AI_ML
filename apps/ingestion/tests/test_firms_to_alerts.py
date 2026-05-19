"""Unit tests for processors/firms_to_alerts.py."""
from __future__ import annotations

from datetime import datetime, timezone

from processors.firms_to_alerts import (
    BRIGHTNESS_CRITICAL_K,
    BRIGHTNESS_HIGH_K,
    CONFIDENCE_HIGH_SCORE,
    CONFIDENCE_NOMINAL_SCORE,
    FRP_CRITICAL_MW,
    FRP_HIGH_MW,
    firms_to_alerts,
)
from sources.nasa_firms import FirmsDetection


def _det(
    *,
    confidence: str | None,
    brightness: float | None = 320.0,
    frp: float | None = 5.0,
    instrument: str = "VIIRS",
) -> FirmsDetection:
    return FirmsDetection(
        latitude=12.5,
        longitude=4.5,
        brightness_k=brightness,
        bright_t31_k=290.0,
        scan=0.5,
        track=0.5,
        detected_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        satellite="Suomi-NPP",
        instrument=instrument,
        confidence=confidence,
        frp=frp,
        daynight="D",
        raw={"version": "2.0NRT"},
    )


def test_low_confidence_viirs_is_filtered_out():
    candidates = firms_to_alerts([_det(confidence="l")], tenant_id="kebbi")
    assert candidates == []


def test_no_confidence_is_filtered_out():
    candidates = firms_to_alerts([_det(confidence=None)], tenant_id="kebbi")
    assert candidates == []


def test_modis_below_min_is_filtered_out():
    candidates = firms_to_alerts(
        [_det(confidence="40", instrument="MODIS")], tenant_id="kebbi"
    )
    assert candidates == []


def test_viirs_nominal_is_promoted_with_nominal_score():
    [c] = firms_to_alerts([_det(confidence="n")], tenant_id="kebbi")
    assert c.alert_type == "fire"
    assert c.confidence_score == CONFIDENCE_NOMINAL_SCORE
    assert c.human_review_required is True


def test_viirs_high_is_promoted_with_high_score():
    [c] = firms_to_alerts([_det(confidence="h")], tenant_id="kebbi")
    assert c.confidence_score == CONFIDENCE_HIGH_SCORE


def test_modis_at_threshold_promoted_high():
    [c] = firms_to_alerts(
        [_det(confidence="85", instrument="MODIS")], tenant_id="kebbi"
    )
    assert c.confidence_score == CONFIDENCE_HIGH_SCORE


def test_severity_critical_when_brightness_above_critical_threshold():
    [c] = firms_to_alerts(
        [_det(confidence="n", brightness=BRIGHTNESS_CRITICAL_K + 1, frp=1.0)],
        tenant_id="kebbi",
    )
    assert c.severity == "critical"


def test_severity_critical_when_frp_above_critical_threshold():
    [c] = firms_to_alerts(
        [_det(confidence="n", brightness=300.0, frp=FRP_CRITICAL_MW + 1)],
        tenant_id="kebbi",
    )
    assert c.severity == "critical"


def test_severity_high_when_only_high_thresholds_cleared():
    [c] = firms_to_alerts(
        [_det(confidence="n", brightness=BRIGHTNESS_HIGH_K + 1, frp=FRP_HIGH_MW)],
        tenant_id="kebbi",
    )
    assert c.severity == "high"


def test_severity_medium_when_only_nominal_no_thermal_signal():
    [c] = firms_to_alerts(
        [_det(confidence="n", brightness=300.0, frp=1.0)],
        tenant_id="kebbi",
    )
    assert c.severity == "medium"


def test_input_hash_stable_for_same_pixel_and_date():
    a = _det(confidence="n")
    b = _det(confidence="n")
    [ca] = firms_to_alerts([a], tenant_id="kebbi")
    [cb] = firms_to_alerts([b], tenant_id="kebbi")
    assert ca.model_input_hash == cb.model_input_hash


def test_input_hash_differs_per_tenant():
    d = _det(confidence="n")
    [ca] = firms_to_alerts([d], tenant_id="kebbi")
    [cb] = firms_to_alerts([d], tenant_id="benue")
    assert ca.model_input_hash != cb.model_input_hash


def test_satellite_source_label_includes_instrument_and_satellite():
    [c] = firms_to_alerts([_det(confidence="n")], tenant_id="kebbi")
    assert "VIIRS" in c.satellite_source
    assert "SUOMI-NPP" in c.satellite_source


def test_pixel_area_ha_from_scan_track():
    [c] = firms_to_alerts([_det(confidence="n")], tenant_id="kebbi")
    assert c.affected_area_ha == 25.0  # 0.5 km * 0.5 km = 0.25 km^2 = 25 ha
