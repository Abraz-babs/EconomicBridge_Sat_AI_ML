"""Tests for the unified intelligence feed (Slice 06.feed).

Pure-Python aggregator + endpoint contract. The DB-touching path is
exercised by the live smoke test in the slice commit body; here we
pin the row→FeedEvent mapping and the static OpenAPI shape (DB-free
per the Python-3.14 audit-log lesson).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from main import app
from services.intelligence_feed import (
    FEED_LOOKBACK_DAYS,
    FeedEvent,
    _normalize_severity,
    _row_to_feed_event,
)


client = TestClient(app)


# ─── Severity normalisation ───────────────────────────────────────────────


def test_severity_canonical_values_unchanged():
    for v in ("low", "medium", "high", "critical"):
        assert _normalize_severity(v) == v


def test_severity_handles_aliases_and_case():
    assert _normalize_severity("CRITICAL") == "critical"
    assert _normalize_severity("Crit") == "critical"
    assert _normalize_severity("moderate") == "medium"
    assert _normalize_severity("LOW_CONFIDENCE") == "low"


def test_severity_falls_back_to_low_for_garbage():
    assert _normalize_severity(None) == "low"
    assert _normalize_severity("") == "low"
    assert _normalize_severity("nonsense") == "low"
    assert _normalize_severity(42) == "low"


# ─── _row_to_feed_event mapping ──────────────────────────────────────────


def _row(**overrides) -> dict:
    base = {
        "kind": "alert_event",
        "subtype": "fire",
        "severity": "high",
        "region": "Argungu",
        "source": "nasa_firms_v1",
        "observed_at": datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
        "metric_value": 45.0,
        "extra": "",
    }
    base.update(overrides)
    return base


def test_alert_event_fire_maps_to_disaster_tag():
    event = _row_to_feed_event("kebbi", _row(kind="alert_event", subtype="fire"))
    assert event is not None
    assert event.kind == "alert_event"
    assert event.tag == "Disaster"
    assert event.severity == "high"
    assert "Heat signature" in event.title
    assert event.tenant_id == "kebbi"


def test_alert_event_encroachment_uses_encroachment_tag():
    event = _row_to_feed_event(
        "kebbi", _row(subtype="encroachment", region="Birnin Kebbi"),
    )
    assert event is not None
    assert event.tag == "Encroachment"
    assert "Encroachment detected" in event.title


def test_ndvi_anomaly_with_flag_titles_with_z_score():
    event = _row_to_feed_event("kebbi", _row(
        kind="ndvi_anomaly", subtype="anomaly", region="maize",
        severity="MEDIUM", metric_value=-2.41, source="ndvi_anomaly_v1",
    ))
    assert event is not None
    assert event.tag == "Agriculture"
    assert "z=-2.41" in event.title
    assert event.severity == "medium"


def test_ndvi_anomaly_clean_severity_floors_to_low():
    event = _row_to_feed_event("kebbi", _row(
        kind="ndvi_anomaly", subtype="clean", severity="HIGH",
        metric_value=0.3,
    ))
    assert event is not None
    assert event.severity == "low"


def test_shock_event_flood_titles_with_region():
    event = _row_to_feed_event("benue", _row(
        kind="shock_event", subtype="flood", region="Agatu",
        severity="critical", source="shock_flood_v1",
        metric_value=120.0,
    ))
    assert event is not None
    assert event.kind == "shock_event"
    assert event.tag == "Disaster"
    assert "Flood" in event.title
    assert "Agatu" in event.title


def test_aid_coverage_renders_with_agency_and_beneficiaries():
    event = _row_to_feed_event("kebbi", _row(
        kind="aid_coverage", region="Argungu", source="wfp_scope_v1",
        metric_value=12500.0, extra="wfp",
    ))
    assert event is not None
    assert event.tag == "Aid"
    assert "WFP" in event.title
    assert "12,500" in event.title


def test_poverty_village_uses_score_for_severity_band():
    event = _row_to_feed_event("kebbi", _row(
        kind="poverty_village", region="Argungu settlement 1",
        source="viirs_v2", metric_value=0.85, extra="Argungu",
    ))
    assert event is not None
    assert event.tag == "Poverty"
    assert event.severity == "high"
    assert "85%" in event.title


def test_row_without_observed_at_returns_none():
    event = _row_to_feed_event("kebbi", _row(observed_at=None))
    assert event is None


def test_observed_at_naive_promoted_to_utc():
    naive = datetime(2026, 5, 20, 12, 0)
    event = _row_to_feed_event("kebbi", _row(observed_at=naive))
    assert event is not None
    assert event.observed_at.tzinfo is not None


# ─── Endpoint OpenAPI contract ───────────────────────────────────────────


def test_feed_endpoint_appears_in_openapi():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/intelligence/feed" in spec["paths"]
    op = spec["paths"]["/api/v1/intelligence/feed"]["get"]
    assert "Overview" in op["summary"]


def test_feed_endpoint_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/intelligence/feed"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100


def test_feed_event_model_declares_all_kinds_and_tags():
    spec = client.get("/api/openapi.json").json()
    schemas = spec["components"]["schemas"]
    event_schema = schemas["FeedEventModel"]
    props = event_schema["properties"]
    assert {"kind", "tenant_id", "title", "region", "tag",
            "severity", "source", "observed_at"} <= set(props.keys())


def test_lookback_window_is_published_in_module_constant():
    """Pin the lookback so a future refactor doesn't silently make the
    Overview tab show a 5-year history."""
    assert FEED_LOOKBACK_DAYS == 90


# ─── Final sanity: FeedEvent dataclass shape ─────────────────────────────


def test_feed_event_dataclass_is_frozen():
    e = FeedEvent(
        kind="alert_event", tenant_id="kebbi", title="x", region=None,
        tag="Disaster", severity="low", source="test",
        observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        e.title = "y"  # type: ignore[misc]
