"""Tests for tasks/satellite_observations_ingest.py.

DB stubbed; Statistical API client stubbed via httpx.MockTransport. What
we pin:
  * Two requests fire per tenant (S1 SAR + S2 NDVI).
  * One UPSERT per non-null StatPoint; None means dropped silently.
  * Unknown tenant raises ValueError.
  * S1 window = 60 days, S2 window = 90 days (matches detector defaults).
  * Source tag is 'sentinel_stat_v1' (live audit trail).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from sources.copernicus import CopernicusClient
from sources.sentinel_statistical import SentinelStatisticalClient
from tasks.satellite_observations_ingest import (
    LIVE_SOURCE,
    ObservationIngestResult,
    S1_WINDOW_DAYS,
    S2_WINDOW_DAYS,
    ingest_tenant,
)


# ─── DB stub ──────────────────────────────────────────────────────────────


class _FakeResult:
    def mappings(self):
        return self

    def all(self):
        return []


class _FakeSession:
    """Stub AsyncSession that records writes without touching a DB."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        sql = " ".join(str(stmt).split())
        self.statements.append((sql, dict(params or {})))
        return _FakeResult()

    async def commit(self) -> None:
        pass


# ─── Statistical API mock ─────────────────────────────────────────────────


def _stat_payload(*, mean_base: float, with_nan_index: int | None = None) -> dict:
    from datetime import timedelta
    rows = []
    base_dt = datetime(2026, 4, 1, tzinfo=timezone.utc)
    for i in range(5):
        is_nan = with_nan_index is not None and i == with_nan_index
        mean = float("nan") if is_nan else mean_base + i * 0.05
        rows.append({
            "interval": {
                "from": (base_dt + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to":   (base_dt + timedelta(days=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "outputs": {
                "default": {"bands": {"B0": {"stats": {
                    "min": mean - 0.05, "max": mean + 0.05, "mean": mean,
                    "stDev": 0.02, "sampleCount": 4096,
                }}}}
            }
        })
    return {"data": rows, "status": "OK"}


def _route(s1_payload: dict, s2_payload: dict, *, with_token: bool = True):
    state = {"calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        state["calls"].append(url)
        if "openid-connect/token" in url:
            return httpx.Response(200, content=json.dumps({
                "access_token": "fake-token",
                "expires_in": 1800,
                "token_type": "Bearer",
            }).encode())
        if "/statistics" in url:
            body = json.loads(request.content.decode())
            ds = body["input"]["data"][0]["type"]
            if ds == "sentinel-1-grd":
                return httpx.Response(200, content=json.dumps(s1_payload).encode())
            if ds == "sentinel-2-l2a":
                return httpx.Response(200, content=json.dumps(s2_payload).encode())
        return httpx.Response(404, content=b"no route")

    return httpx.MockTransport(handler), state


@pytest.fixture
def configured(monkeypatch):
    from config import get_settings
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "cid")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Happy path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_writes_s1_and_s2_for_pilot(configured):
    s1 = _stat_payload(mean_base=-11.5)
    s2 = _stat_payload(mean_base=0.45)
    transport, _ = _route(s1, s2)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)

    session = _FakeSession()
    result = await ingest_tenant(
        session, tenant_id="kebbi",
        statistical_client=client,
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    assert isinstance(result, ObservationIngestResult)
    assert result.tenant_id == "kebbi"
    assert result.s1_points == 5
    assert result.s2_points == 5
    assert result.s1_window_days == S1_WINDOW_DAYS
    assert result.s2_window_days == S2_WINDOW_DAYS


@pytest.mark.asyncio
async def test_ingest_drops_nan_intervals(configured):
    """Fully-masked S2 intervals (cloud cover, no acquisition) → no row."""
    s1 = _stat_payload(mean_base=-11.5)
    s2 = _stat_payload(mean_base=0.45, with_nan_index=2)
    transport, _ = _route(s1, s2)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)

    session = _FakeSession()
    result = await ingest_tenant(
        session, tenant_id="kebbi",
        statistical_client=client,
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    assert result.s1_points == 5
    assert result.s2_points == 4   # one masked → dropped


@pytest.mark.asyncio
async def test_ingest_emits_set_search_path_plus_upserts(configured):
    """One SET search_path per tenant + one INSERT per non-null point."""
    s1 = _stat_payload(mean_base=-11.5)
    s2 = _stat_payload(mean_base=0.45)
    transport, _ = _route(s1, s2)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)

    session = _FakeSession()
    await ingest_tenant(
        session, tenant_id="kebbi",
        statistical_client=client,
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    sets = [s for s, _ in session.statements if s.startswith("SET search_path")]
    inserts = [s for s, _ in session.statements if s.startswith("INSERT INTO satellite_observations")]
    assert len(sets) == 1
    assert len(inserts) == 10   # 5 S1 + 5 S2


@pytest.mark.asyncio
async def test_ingest_tags_rows_with_live_source(configured):
    s1 = _stat_payload(mean_base=-11.5)
    s2 = _stat_payload(mean_base=0.45)
    transport, _ = _route(s1, s2)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)

    session = _FakeSession()
    await ingest_tenant(
        session, tenant_id="kebbi",
        statistical_client=client,
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )

    inserts = [
        params for sql, params in session.statements
        if sql.startswith("INSERT INTO satellite_observations")
    ]
    sources = {p["source"] for p in inserts}
    assert sources == {LIVE_SOURCE}


@pytest.mark.asyncio
async def test_ingest_can_skip_sar_or_ndvi(configured):
    """include_sar=False / include_ndvi=False should skip the corresponding
    Statistical API call entirely (PU savings on partial refreshes)."""
    s1 = _stat_payload(mean_base=-11.5)
    s2 = _stat_payload(mean_base=0.45)
    transport, state = _route(s1, s2)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)

    session = _FakeSession()
    result = await ingest_tenant(
        session, tenant_id="kebbi",
        statistical_client=client,
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        include_sar=False,
    )
    assert result.s1_points == 0
    assert result.s2_points == 5


# ─── Validation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_rejects_unknown_tenant(configured):
    transport, _ = _route(_stat_payload(mean_base=0), _stat_payload(mean_base=0))
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)
    session = _FakeSession()
    with pytest.raises(ValueError, match="Unknown tenant_id"):
        await ingest_tenant(
            session, tenant_id="atlantis",
            statistical_client=client,
            end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )
