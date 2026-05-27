"""Unit tests for the small pure helpers in tasks/conflict_pipeline.py.

The orchestration in `run_for_tenant` is exercised by the live smoke
test in the build runbook — too much mocking surface to be worth a
unit-level integration test (mocked DB + mocked HTTP + 10 tenant fixtures).
"""
from __future__ import annotations

import pytest

from processors.conflict_features import build_cluster, HeatDetection
from tasks.conflict_pipeline import (
    _TENANT_CONFLICT_RISK,
    _build_input_hash,
    severity_for,
)


# ─── severity_for ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prediction,expected",
    [
        (0.99, "critical"),
        (0.85, "critical"),
        (0.849, "high"),
        (0.70, "high"),
        (0.699, "medium"),
        (0.55, "medium"),
        (0.549, "low"),
        (0.0, "low"),
    ],
)
def test_severity_for_band_boundaries(prediction: float, expected: str):
    assert severity_for(prediction) == expected


# ─── _build_input_hash ─────────────────────────────────────────────────────


def _cluster_at(lat: float, lon: float):
    return build_cluster(
        tenant_id="kebbi",
        lat_bucket=int(lat * 10), lon_bucket=int(lon * 10),
        members=[HeatDetection(
            detection_id="d1", latitude=lat, longitude=lon, brightness_k=320.0,
        )],
        tenant_conflict_risk="critical",
        historical_incident_count=0,
        prior_alert_points=[],
    )


def test_input_hash_is_stable_for_same_cluster_day_version():
    c = _cluster_at(12.0, 4.5)
    a = _build_input_hash(cluster=c, model_version="v1", bucket_date="2026-05-20")
    b = _build_input_hash(cluster=c, model_version="v1", bucket_date="2026-05-20")
    assert a == b


def test_input_hash_changes_on_different_day():
    c = _cluster_at(12.0, 4.5)
    a = _build_input_hash(cluster=c, model_version="v1", bucket_date="2026-05-20")
    b = _build_input_hash(cluster=c, model_version="v1", bucket_date="2026-05-21")
    assert a != b


def test_input_hash_changes_on_different_model_version():
    c = _cluster_at(12.0, 4.5)
    a = _build_input_hash(cluster=c, model_version="v1", bucket_date="2026-05-20")
    b = _build_input_hash(cluster=c, model_version="v2", bucket_date="2026-05-20")
    assert a != b


def test_input_hash_changes_on_different_cluster():
    a_cluster = _cluster_at(12.0, 4.5)
    b_cluster = _cluster_at(12.5, 4.5)
    a = _build_input_hash(cluster=a_cluster, model_version="v1", bucket_date="2026-05-20")
    b = _build_input_hash(cluster=b_cluster, model_version="v1", bucket_date="2026-05-20")
    assert a != b


# ─── _TENANT_CONFLICT_RISK ────────────────────────────────────────────────


def test_tenant_risk_map_covers_all_pilots():
    from db import PILOT_TENANT_IDS
    missing = PILOT_TENANT_IDS - set(_TENANT_CONFLICT_RISK)
    assert not missing, f"missing conflict_risk for: {sorted(missing)}"


def test_tenant_risk_map_uses_canonical_tiers():
    assert set(_TENANT_CONFLICT_RISK.values()) <= {
        "critical", "high", "medium", "low",
    }


# ─── Slice 16: ingestion_runs tracking ────────────────────────────────────


def test_run_source_label_matches_dashboard_filter():
    """The Admin scheduler panel filters `/scheduler/runs/recent` by
    source=conflict_pipeline_v1 to pull conflict runs out from the
    FIRMS rows. Lock the label here so a refactor renaming it to,
    say, 'conflict_pipeline' or 'conflict_v2' fails this guard before
    the dashboard goes silently empty."""
    from tasks.conflict_pipeline import RUN_SOURCE
    assert RUN_SOURCE == "conflict_pipeline_v1"


def test_run_for_tenant_default_trigger_is_manual():
    """Direct calls via POST /ingest/conflict (Slice 10 manual trigger)
    must end up tagged trigger='manual' in ingestion_runs. The
    scheduled cron explicitly passes trigger='scheduled'; everything
    else defaults to 'manual' so the dashboard's Trigger column
    distinguishes 'someone clicked Run now' from 'overnight job fired'."""
    import inspect
    from tasks.conflict_pipeline import run_for_tenant
    sig = inspect.signature(run_for_tenant)
    assert sig.parameters["trigger"].default == "manual"
