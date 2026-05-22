"""Tests for tasks/poverty_ingest.py — orchestration + upsert behaviour.

DB is stubbed; HTTP clients are stubbed at the catalog-client level (we
inject pre-built `BlackMarbleClient` / `WorldPopClient` instances using
`httpx.MockTransport`). What we pin:

  * Settlements list: 8 stable points per tenant (4 LGAs × 2).
  * When VIIRS returns a granule + WorldPop returns a layer → every row
    written with source='viirs_v2'.
  * No granule + no layer → every row written with source='seed_v1'.
  * Upsert deletes before insert (one DELETE + one INSERT per signal).
  * Unknown tenant raises ValueError.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from sources.viirs_black_marble import BlackMarbleClient
from sources.worldpop import WorldPopClient
from tasks.poverty_ingest import (
    LGA_SAMPLE,
    TENANT_CENTROIDS,
    PovertyIngestResult,
    ingest_tenant,
    settlements_for,
)


# ─── Settlement layout ────────────────────────────────────────────────────


def test_settlements_for_returns_eight_per_pilot():
    for tenant in TENANT_CENTROIDS:
        sites = settlements_for(tenant)
        assert len(sites) == 8, f"{tenant}: {len(sites)}"


def test_settlements_anchored_to_tenant_centroid():
    sites = settlements_for("kebbi")
    centroid = TENANT_CENTROIDS["kebbi"]
    for s in sites:
        assert abs(s.lon - centroid[0]) < 1.0
        assert abs(s.lat - centroid[1]) < 1.0


def test_settlements_use_lga_sample():
    for tenant, lgas in LGA_SAMPLE.items():
        names = {s.lga for s in settlements_for(tenant)}
        assert names <= set(lgas), f"{tenant}: {names - set(lgas)}"


def test_settlements_are_deterministic():
    a = settlements_for("benue")
    b = settlements_for("benue")
    assert a == b


# ─── DB stub ──────────────────────────────────────────────────────────────


class _NoMatchResult:
    """Pass-through result for stub session.execute()."""

    def mappings(self):
        return self

    def all(self) -> list[Any]:
        return []


class _FakeSession:
    """Stub AsyncSession that records writes without touching a DB."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        sql = " ".join(str(stmt).split())
        self.statements.append((sql, dict(params or {})))
        return _NoMatchResult()

    async def commit(self) -> None:
        pass


def _viirs_client_with_granule() -> BlackMarbleClient:
    # h17v07 covers Kebbi (lon -4..6, lat 10..20); h16v07 covers Senegal.
    payload = [
        {
            "name": "VNP46A2.A2026140.h17v07.001.x.h5",
            "size": 12_345_678,
            "downloadsLink": "https://ladsweb...",
        }
    ]
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=json.dumps(payload).encode())
    )
    return BlackMarbleClient(http=httpx.AsyncClient(transport=transport))


def _viirs_client_empty() -> BlackMarbleClient:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"[]")
    )
    return BlackMarbleClient(http=httpx.AsyncClient(transport=transport))


def _worldpop_client_with_layer() -> WorldPopClient:
    payload = {"data": [{
        "id": 42, "iso3": "NGA", "popyear": 2024,
        "title": "Nigeria population 2024", "resolution": "100m",
        "data_file": "https://data.worldpop.org/.../nga.tif",
        "file_size": 87_654_321,
    }]}
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=json.dumps(payload).encode())
    )
    return WorldPopClient(http=httpx.AsyncClient(transport=transport))


def _worldpop_client_empty() -> WorldPopClient:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=b'{"data":[]}')
    )
    return WorldPopClient(http=httpx.AsyncClient(transport=transport))


# ─── ingest_tenant integration ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_writes_viirs_v2_when_both_signals_present(monkeypatch):
    # No token needed for the WorldPop side; force Earthdata token so VIIRS
    # fires the HTTP path instead of returning [] early.
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    from config import get_settings
    get_settings.cache_clear()

    session = _FakeSession()
    result = await ingest_tenant(
        session, tenant_id="kebbi",
        viirs_client=_viirs_client_with_granule(),
        worldpop_client=_worldpop_client_with_layer(),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    get_settings.cache_clear()

    assert isinstance(result, PovertyIngestResult)
    assert result.tenant_id == "kebbi"
    assert result.viirs_granule_id is not None
    assert result.worldpop_dataset_id == 42
    assert result.rows_written == 8
    assert result.sources_observed == ("viirs_v2",)


@pytest.mark.asyncio
async def test_ingest_falls_back_to_seed_when_no_catalogs(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    from config import get_settings
    get_settings.cache_clear()

    session = _FakeSession()
    result = await ingest_tenant(
        session, tenant_id="kebbi",
        viirs_client=_viirs_client_empty(),
        worldpop_client=_worldpop_client_empty(),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    get_settings.cache_clear()

    assert result.viirs_granule_id is None
    assert result.worldpop_dataset_id is None
    assert result.sources_observed == ("seed_v1",)


@pytest.mark.asyncio
async def test_ingest_emits_one_delete_plus_one_insert_per_signal(monkeypatch):
    """8 settlements → 8 DELETEs + 8 INSERTs + 1 SET search_path."""
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    from config import get_settings
    get_settings.cache_clear()

    session = _FakeSession()
    await ingest_tenant(
        session, tenant_id="kebbi",
        viirs_client=_viirs_client_with_granule(),
        worldpop_client=_worldpop_client_with_layer(),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    get_settings.cache_clear()

    deletes = [s for s, _ in session.statements if s.startswith("DELETE FROM poverty_villages")]
    inserts = [s for s, _ in session.statements if s.startswith("INSERT INTO poverty_villages")]
    set_paths = [s for s, _ in session.statements if s.startswith("SET search_path")]
    assert len(deletes) == 8
    assert len(inserts) == 8
    assert len(set_paths) == 1


@pytest.mark.asyncio
async def test_ingest_rejects_unknown_tenant():
    session = _FakeSession()
    with pytest.raises(ValueError, match="Unknown tenant_id"):
        await ingest_tenant(
            session, tenant_id="atlantis",
            viirs_client=_viirs_client_empty(),
            worldpop_client=_worldpop_client_empty(),
        )


@pytest.mark.asyncio
async def test_ingest_for_senegal_uses_country_iso(monkeypatch):
    """Senegal tenant should hit WorldPop with SEN — confirms tenant→ISO3 wiring."""
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    from config import get_settings
    get_settings.cache_clear()

    captured: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(str(req.url))
        return httpx.Response(200, content=b'{"data":[]}')

    worldpop = WorldPopClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    session = _FakeSession()

    await ingest_tenant(
        session, tenant_id="senegal",
        viirs_client=_viirs_client_empty(),
        worldpop_client=worldpop,
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    get_settings.cache_clear()

    assert any("SEN" in url for url in captured)
