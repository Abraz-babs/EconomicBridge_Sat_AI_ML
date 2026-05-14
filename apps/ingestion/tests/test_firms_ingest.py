"""Integration tests for the FIRMS ingest task.

Require:
  - Postgres reachable
  - Migrations applied through 0004
  (`pytest -m integration` from apps/ingestion/)

These tests exercise the full path: mock FIRMS client -> ingest_firms_for_tenant
-> public.ingestion_runs row + tenant_kebbi.heat_signatures rows.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from main import app
from sources.nasa_firms import _mock_detections, PILOT_BBOX

pytestmark = pytest.mark.integration

client = TestClient(app)


def _sync_url() -> str:
    """Convert the async DATABASE_URL to a sync one for setup/teardown."""
    from config import get_settings
    return get_settings().database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


def test_firms_trigger_writes_to_kebbi_heat_signatures() -> None:
    response = client.post(
        "/api/v1/ingest/firms",
        json={"tenant_id": "kebbi", "day_range": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["records_ingested"] >= 1
    assert body["dry_run"] is False
    run_id = body["run_id"]

    # Verify the public.ingestion_runs row landed
    engine = create_engine(_sync_url(), future=True)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT status, source, tenant_id, records_ingested "
                    "FROM public.ingestion_runs WHERE id = :id"
                ),
                {"id": run_id},
            ).one()
            assert row.status == "succeeded"
            assert row.tenant_id == "kebbi"
            assert row.records_ingested >= 1
        # And the heat_signatures rows
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            cnt = conn.execute(
                text(
                    "SELECT COUNT(*) FROM heat_signatures "
                    "WHERE ingestion_run_id = :id"
                ),
                {"id": run_id},
            ).scalar_one()
            assert int(cnt) == body["records_ingested"]
    finally:
        # Clean up the run + its detections so re-runs stay deterministic
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO tenant_kebbi, public"))
            conn.execute(
                text("DELETE FROM heat_signatures WHERE ingestion_run_id = :id"),
                {"id": run_id},
            )
            conn.execute(text("SET search_path TO public"))
            conn.execute(
                text("DELETE FROM public.ingestion_runs WHERE id = :id"),
                {"id": run_id},
            )
        engine.dispose()


def test_firms_trigger_dry_run_does_not_write_detections() -> None:
    response = client.post(
        "/api/v1/ingest/firms",
        json={"tenant_id": "kebbi", "dry_run": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["dry_run"] is True
    # records_ingested reflects "would have written" count in dry-run mode
    assert body["records_ingested"] == len(_mock_detections(PILOT_BBOX["kebbi"]))

    # Cleanup the run row (no detections written)
    engine = create_engine(_sync_url(), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM public.ingestion_runs WHERE id = :id"),
                {"id": body["run_id"]},
            )
    finally:
        engine.dispose()


def test_firms_trigger_unknown_tenant_returns_404() -> None:
    response = client.post(
        "/api/v1/ingest/firms",
        json={"tenant_id": "atlantis"},
    )
    assert response.status_code == 404
    assert "atlantis" in response.text


def test_firms_trigger_validates_day_range() -> None:
    response = client.post(
        "/api/v1/ingest/firms",
        json={"tenant_id": "kebbi", "day_range": 99},
    )
    assert response.status_code == 422
