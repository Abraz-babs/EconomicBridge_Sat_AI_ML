"""Tests for POST /api/v1/ingest/conflict — manual conflict pipeline.

Mirrors the test_firms_ingest pattern: DB-free contract assertions plus
an OpenAPI schema check that locks the response shape. The full
pipeline behaviour (clustering + ML calls + alert writes) is covered
elsewhere in test_conflict_pipeline_unit.py — this file only verifies
the HTTP plumbing of the new trigger.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_conflict_trigger_endpoint_exists_in_openapi():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/ingest/conflict" in spec["paths"]


def test_conflict_trigger_unknown_tenant_returns_404():
    r = client.post(
        "/api/v1/ingest/conflict",
        json={"tenant_id": "atlantis"},
    )
    assert r.status_code == 404
    assert "atlantis" in r.text


def test_conflict_trigger_requires_tenant_id():
    r = client.post("/api/v1/ingest/conflict", json={})
    assert r.status_code == 422


def test_conflict_trigger_rejects_lookback_above_max():
    """Hard cap protects the heat_signatures index from a 1000-day scan."""
    r = client.post(
        "/api/v1/ingest/conflict",
        json={"tenant_id": "kebbi", "lookback_days": 365},
    )
    assert r.status_code == 422


def test_conflict_trigger_rejects_zero_lookback():
    r = client.post(
        "/api/v1/ingest/conflict",
        json={"tenant_id": "kebbi", "lookback_days": 0},
    )
    assert r.status_code == 422


def test_conflict_trigger_response_schema_locked():
    """Pin the response shape so the dashboard / scheduler-overview UI
    doesn't break on a silent rename."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ConflictTriggerResponse"]
    props = schema["properties"]
    expected = {
        "tenant_id", "clusters_built", "predictions_made",
        "alerts_written", "skipped_below_threshold",
        "skipped_capped", "skipped_duplicates", "error",
    }
    assert expected <= set(props.keys())


def test_conflict_trigger_lookback_default_is_seven_days():
    """The scheduled daily job uses a 7-day window; the manual endpoint
    should default to the same so behaviour matches the cron unless
    explicitly overridden."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ConflictTriggerRequest"]
    lookback = schema["properties"]["lookback_days"]
    assert lookback.get("default") == 7
    assert lookback.get("minimum") == 1
    assert lookback.get("maximum") == 90
