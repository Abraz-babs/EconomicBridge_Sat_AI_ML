"""Tests for services/live_satellite.py (Slice 05.live).

Stubs the session entirely — we're testing the SHAPE of the queries +
the reshape into FloodSeriesPoint / NdviSample tuples, not the SQL
itself (the SQL was already verified by the end-to-end smoke test
on the dev DB).

HTTP contract tests for the data_source flag are static OpenAPI checks,
per the Python-3.14 audit-log lesson.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from main import app
from services.live_satellite import (
    LIVE_SOURCE,
    LiveDataMissingError,
    load_flood_series,
    load_ndvi_series,
)
from services.ndvi_anomaly import NdviSample
from services.shock_detector import FloodSeriesPoint


client = TestClient(app)


# ─── Session stub ────────────────────────────────────────────────────────


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        sql = " ".join(str(stmt).split())
        self.queries.append((sql, dict(params or {})))
        return _Result(self._rows)


# ─── load_flood_series ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_flood_series_reshapes_rows():
    rows = [
        {"observed_at": date(2026, 4, i + 1), "sar_backscatter_db": -11.0 + i * 0.1}
        for i in range(20)
    ]
    session = _FakeSession(rows)
    series = await load_flood_series(session)
    assert isinstance(series, tuple)
    assert len(series) == 20
    assert all(isinstance(p, FloodSeriesPoint) for p in series)
    assert series[0].backscatter_db == pytest.approx(-11.0)
    assert series[-1].observed_at == date(2026, 4, 20)


@pytest.mark.asyncio
async def test_load_flood_series_pins_live_source_in_query():
    """We must filter by source='sentinel_stat_v1' so synthetic +
    detector-fallback rows don't accidentally feed the live detector."""
    session = _FakeSession(rows=[
        {"observed_at": date(2026, 4, i + 1), "sar_backscatter_db": -11.0}
        for i in range(20)
    ])
    await load_flood_series(session)
    params = session.queries[0][1]
    assert params["source"] == LIVE_SOURCE


@pytest.mark.asyncio
async def test_load_flood_series_raises_when_sparse():
    session = _FakeSession(rows=[
        {"observed_at": date(2026, 4, 1), "sar_backscatter_db": -11.0},
    ])
    with pytest.raises(LiveDataMissingError, match="only 1 SAR rows"):
        await load_flood_series(session)


@pytest.mark.asyncio
async def test_load_flood_series_floor_override():
    """min_points lets the caller relax the gate for a partial-data test
    or a tenant with less frequent SAR coverage."""
    session = _FakeSession(rows=[
        {"observed_at": date(2026, 4, i + 1), "sar_backscatter_db": -11.0}
        for i in range(5)
    ])
    series = await load_flood_series(session, min_points=3)
    assert len(series) == 5


# ─── load_ndvi_series ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_ndvi_series_reshapes_rows():
    from datetime import timedelta
    base = date(2026, 3, 1)
    rows = [
        {"observed_at": base + timedelta(days=i), "ndvi_mean": 0.30 + i * 0.005}
        for i in range(35)
    ]
    session = _FakeSession(rows)
    series = await load_ndvi_series(session)
    assert isinstance(series, tuple)
    assert len(series) == 35
    assert all(isinstance(p, NdviSample) for p in series)
    assert series[0].ndvi == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_load_ndvi_series_raises_when_sparse():
    session = _FakeSession(rows=[
        {"observed_at": date(2026, 4, 1), "ndvi_mean": 0.45},
    ])
    with pytest.raises(LiveDataMissingError, match="only 1 NDVI rows"):
        await load_ndvi_series(session)


# ─── HTTP contract: data_source field in OpenAPI ──────────────────────────


def test_shock_scan_request_has_data_source_field():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ShockScanRequest"]
    assert "data_source" in schema["properties"]


def test_ndvi_scan_request_has_data_source_field():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["NdviScanRequest"]
    assert "data_source" in schema["properties"]


def test_shock_data_source_enum_locked_to_synthetic_live():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ShockScanRequest"]
    field = schema["properties"]["data_source"]
    if "$ref" in field:
        ref = field["$ref"].split("/")[-1]
        enum = spec["components"]["schemas"][ref]["enum"]
    else:
        enum = field.get("enum", [])
    assert set(enum) == {"synthetic", "live"}


def test_ndvi_data_source_default_is_synthetic():
    """Existing callers must not break — default must stay synthetic."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["NdviScanRequest"]
    field = schema["properties"]["data_source"]
    assert field.get("default") == "synthetic"
