"""Unit tests for sources/worldpop.py.

WorldPop REST is anonymous, but we still mock httpx (CLAUDE.md §11):
the production CI must never call the real API. What we pin:

  * `configured` is unconditionally True (no auth).
  * Real WorldPop row shape → WorldPopLayer fields populated.
  * Unknown tenant → latest_layer_for_tenant returns None (no raise).
  * Mixed resolution formats normalise to metres.
  * 404 (country/year missing) → []; other non-200 → WorldPopError.
  * Year filter applies post-fetch.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sources.worldpop import (
    TENANT_TO_ISO3,
    WorldPopClient,
    WorldPopError,
    _resolution_metres,
)


def _layer_row(
    *,
    id_: int,
    iso3: str = "NGA",
    year: int = 2024,
    resolution: str = "100m",
) -> dict[str, Any]:
    return {
        "id": id_,
        "iso3": iso3,
        "popyear": year,
        "title": f"Nigeria population {year}",
        "resolution": resolution,
        "data_file": (
            f"https://data.worldpop.org/GIS/Population/Global_2020/"
            f"{iso3}/{iso3.lower()}_ppp_{year}.tif"
        ),
        "file_size": 87_654_321,
    }


def _route(payload: Any, *, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 200:
            return httpx.Response(200, content=json.dumps(payload).encode())
        return httpx.Response(status_code, content=b"err")

    return httpx.MockTransport(handler)


# ─── Configuration ────────────────────────────────────────────────────────


def test_worldpop_is_unconditionally_configured():
    assert WorldPopClient().configured is True


# ─── Parser ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_layers_parses_row_shape():
    payload = {"data": [_layer_row(id_=42), _layer_row(id_=43, year=2023)]}
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(payload)))
    layers = await client.list_layers(iso3="NGA")
    assert len(layers) == 2
    assert layers[0].year == 2024   # newest first
    assert layers[0].iso3 == "NGA"
    assert layers[0].resolution_m == 100
    assert layers[0].download_url.endswith("ppp_2024.tif")
    assert layers[0].file_size_bytes == 87_654_321


@pytest.mark.asyncio
async def test_list_layers_year_filter():
    payload = {"data": [
        _layer_row(id_=1, year=2024),
        _layer_row(id_=2, year=2023),
        _layer_row(id_=3, year=2020),
    ]}
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(payload)))
    layers = await client.list_layers(iso3="NGA", year=2023)
    assert len(layers) == 1
    assert layers[0].year == 2023


@pytest.mark.asyncio
async def test_list_layers_drops_malformed_rows():
    payload = {"data": [
        {"id": "not-an-int", "iso3": "NGA"},
        {"id": 1, "iso3": "BAD"},          # ISO not length-3 (still valid below)
        {"id": 2, "iso3": "NG"},           # too short
        {"id": 3},                          # missing iso3
        _layer_row(id_=99),
    ]}
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(payload)))
    layers = await client.list_layers(iso3="NGA")
    assert len(layers) == 1
    assert layers[0].dataset_id == 99


@pytest.mark.asyncio
async def test_list_layers_caps_results():
    payload = {"data": [_layer_row(id_=i, year=2010 + i) for i in range(30)]}
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(payload)))
    layers = await client.list_layers(iso3="NGA", max_results=5)
    assert len(layers) == 5


# ─── Tenant resolution ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_latest_layer_for_known_tenant():
    payload = {"data": [_layer_row(id_=10, iso3="GHA", year=2024)]}
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(payload)))
    layer = await client.latest_layer_for_tenant("ghana")
    assert layer is not None
    assert layer.iso3 == "GHA"


@pytest.mark.asyncio
async def test_latest_layer_for_unknown_tenant_returns_none():
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route({"data": []})))
    layer = await client.latest_layer_for_tenant("atlantis")
    assert layer is None


@pytest.mark.asyncio
async def test_latest_layer_returns_none_when_catalog_empty():
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route({"data": []})))
    layer = await client.latest_layer_for_tenant("kebbi")
    assert layer is None


def test_all_pilot_tenants_have_iso3_mapping():
    pilots = {
        "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
        "nasarawa", "fct", "ghana", "senegal",
    }
    assert pilots <= set(TENANT_TO_ISO3.keys())


# ─── HTTP error handling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_returns_empty_list():
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(None, status_code=404)))
    layers = await client.list_layers(iso3="NGA")
    assert layers == []


@pytest.mark.asyncio
async def test_5xx_raises_worldpop_error():
    client = WorldPopClient(http=httpx.AsyncClient(transport=_route(None, status_code=503)))
    with pytest.raises(WorldPopError, match="503"):
        await client.list_layers(iso3="NGA")


@pytest.mark.asyncio
async def test_non_json_body_raises_worldpop_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")
    client = WorldPopClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(WorldPopError, match="non-JSON"):
        await client.list_layers(iso3="NGA")


# ─── Helpers ──────────────────────────────────────────────────────────────


def test_resolution_metres_handles_common_formats():
    assert _resolution_metres("100m") == 100
    assert _resolution_metres("1km") == 1000
    assert _resolution_metres("30s") == 1000   # 30 arc-second ≈ 1 km
    assert _resolution_metres(100) == 100
    assert _resolution_metres(None) is None
    assert _resolution_metres("garbage") is None
