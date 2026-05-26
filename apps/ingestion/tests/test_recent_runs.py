"""Tests for GET /api/v1/scheduler/runs/recent — pipeline observability."""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_recent_runs_endpoint_exists_in_openapi():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/scheduler/runs/recent" in spec["paths"]


def test_recent_runs_response_schema_locked():
    """Pin the response shape so dashboards depending on this don't
    break on a silent rename."""
    spec = client.get("/api/openapi.json").json()
    response = spec["components"]["schemas"]["RunsRecentResponse"]
    assert "rows" in response["properties"]
    assert "total" in response["properties"]

    row = spec["components"]["schemas"]["IngestionRunRow"]["properties"]
    expected = {
        "run_id", "tenant_id", "source", "status", "trigger",
        "started_at", "finished_at", "duration_seconds",
        "records_ingested", "error_message",
    }
    assert expected <= set(row.keys())


def test_recent_runs_declares_limit_constraints():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/scheduler/runs/recent"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 200


def test_recent_runs_accepts_tenant_id_filter():
    spec = client.get("/api/openapi.json").json()
    params = spec["paths"]["/api/v1/scheduler/runs/recent"]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert {"tenant_id", "source", "limit"} <= names


def test_worldpop_weekly_is_a_triggerable_job():
    """Slice 09 added the WorldPop weekly job; Slice 10 wires it into the
    /scheduler/jobs/{id}/run manual-trigger map so admins can fire it on
    demand alongside FIRMS and the conflict pipeline."""
    from routers.jobs import _TRIGGERABLE_JOBS
    from scheduler import JOB_ID_WORLDPOP_WEEKLY
    assert JOB_ID_WORLDPOP_WEEKLY in _TRIGGERABLE_JOBS
