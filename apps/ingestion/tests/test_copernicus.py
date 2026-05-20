"""Unit tests for sources/copernicus.py.

Mocks every network call (CLAUDE.md §11) — no live OAuth, no live STAC.
We do not test the real CDSE behaviour here; that's the smoke test in
the build runbook. What we DO pin:

  * Token caching: a second call within TTL reuses the cached token,
    but the cache invalidates near expiry (skew-aware).
  * STAC parser: real CDSE feature shape → SentinelScene fields.
  * Cloud-cover filter: applied client-side.
  * MGRS tile fallback: parsed from the SAFE id when not in properties.
  * Error surfacing: non-200 from OAuth / STAC raise CopernicusError.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from config import get_settings
from sources.copernicus import (
    CopernicusClient,
    CopernicusError,
    SentinelScene,
    _extract_mgrs_tile,
    _parse_datetime,
    _parse_feature,
    _to_iso_utc,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


def _fake_token_payload(expires_in: int = 1800) -> dict[str, Any]:
    return {
        "access_token": "fake-token-xyz",
        "token_type": "Bearer",
        "expires_in": expires_in,
    }


def _fake_stac_payload(features: list[dict] | None = None) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": features
        or [
            {
                "id": "S2A_MSIL2A_20260519T102601_N0512_R022_T31PEN_20260519T181155.SAFE",
                "bbox": [3.8, 11.4, 5.1, 12.7],
                "properties": {
                    "datetime": "2026-05-19T10:28:03.953Z",
                    "eo:cloud_cover": 12.5,
                },
                "links": [
                    {
                        "rel": "self",
                        "href": "https://sh.dataspace.copernicus.eu/api/v1/catalog/.../S2A_X.SAFE",
                    }
                ],
            }
        ],
    }


def _route(handlers: dict[str, list[httpx.Response]]) -> httpx.MockTransport:
    """Route requests by URL substring; each substring has a queue of responses."""
    queues = {k: list(v) for k, v in handlers.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for needle, queue in queues.items():
            if needle in url and queue:
                return queue.pop(0)
        return httpx.Response(404, content=b"no route")

    return httpx.MockTransport(handler)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "cid")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Configuration ─────────────────────────────────────────────────────────


def test_client_configured_only_when_both_creds_set(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        assert CopernicusClient().configured is False
    finally:
        get_settings.cache_clear()


def test_client_configured_when_both_creds_present(configured):
    assert CopernicusClient().configured is True


@pytest.mark.asyncio
async def test_access_token_raises_when_unconfigured(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(CopernicusError, match="not configured"):
            await CopernicusClient().access_token()
    finally:
        get_settings.cache_clear()


# ─── Token caching ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_access_token_caches_within_ttl(configured):
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps(_fake_token_payload(1800)).encode()),
            # Sentinel — if the client fetched a second time we'd hit this.
            httpx.Response(500, content=b"should not be reached"),
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        t1 = await client.access_token(now=1_000_000.0)
        t2 = await client.access_token(now=1_000_500.0)  # 500s later, well within TTL
    assert t1 == t2 == "fake-token-xyz"


@pytest.mark.asyncio
async def test_access_token_refreshes_within_skew_window(configured):
    # First token expires at 1_001_800. Skew is 60s. Second fetch at
    # 1_001_745 (=55s before stated expiry) should trigger refresh.
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps({
                "access_token": "tok-1", "expires_in": 1800, "token_type": "Bearer",
            }).encode()),
            httpx.Response(200, content=json.dumps({
                "access_token": "tok-2", "expires_in": 1800, "token_type": "Bearer",
            }).encode()),
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        t1 = await client.access_token(now=1_000_000.0)
        t2 = await client.access_token(now=1_001_745.0)
    assert t1 == "tok-1"
    assert t2 == "tok-2"


@pytest.mark.asyncio
async def test_oauth_non_200_raises(configured):
    transport = _route({
        "openid-connect/token": [httpx.Response(401, content=b'{"error":"invalid_client"}')],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        with pytest.raises(CopernicusError, match="CDSE OAuth 401"):
            await client.access_token()


@pytest.mark.asyncio
async def test_oauth_malformed_body_raises(configured):
    transport = _route({
        "openid-connect/token": [httpx.Response(200, content=b'{"not":"a token"}')],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        with pytest.raises(CopernicusError, match="malformed body"):
            await client.access_token()


# ─── STAC search ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_scenes_returns_parsed_features(configured):
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps(_fake_token_payload()).encode())
        ],
        "catalog/1.0.0/search": [
            httpx.Response(200, content=json.dumps(_fake_stac_payload()).encode())
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        scenes = await client.search_scenes(
            bbox=(3.6, 10.8, 5.5, 13.2),
            start=datetime(2026, 5, 13, tzinfo=timezone.utc),
            end=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
    assert len(scenes) == 1
    s = scenes[0]
    assert s.scene_id.startswith("S2A_MSIL2A_")
    assert s.collection == "sentinel-2-l2a"
    assert s.cloud_cover_pct == 12.5
    assert s.mgrs_tile == "31PEN"
    assert s.self_href and s.self_href.startswith("https://sh.dataspace")
    assert s.captured_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_search_scenes_filters_high_cloud_cover(configured):
    features = [
        # Clear
        {
            "id": "S2A_..._T31PEN_...SAFE",
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2026-05-19T10:00:00Z", "eo:cloud_cover": 10.0},
        },
        # Cloudy
        {
            "id": "S2A_..._T31PFP_...SAFE",
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2026-05-18T10:00:00Z", "eo:cloud_cover": 92.0},
        },
    ]
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps(_fake_token_payload()).encode())
        ],
        "catalog/1.0.0/search": [
            httpx.Response(200, content=json.dumps(_fake_stac_payload(features)).encode())
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        scenes = await client.search_scenes(
            bbox=(0, 0, 1, 1),
            start=datetime(2026, 5, 13, tzinfo=timezone.utc),
            end=datetime(2026, 5, 20, tzinfo=timezone.utc),
            max_cloud_cover_pct=30.0,
        )
    assert len(scenes) == 1
    assert scenes[0].cloud_cover_pct == 10.0


@pytest.mark.asyncio
async def test_search_scenes_sorts_newest_first(configured):
    features = [
        {"id": "old", "bbox": [0,0,1,1],
         "properties": {"datetime": "2026-05-13T00:00:00Z", "eo:cloud_cover": 5}},
        {"id": "new", "bbox": [0,0,1,1],
         "properties": {"datetime": "2026-05-19T00:00:00Z", "eo:cloud_cover": 5}},
    ]
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps(_fake_token_payload()).encode())
        ],
        "catalog/1.0.0/search": [
            httpx.Response(200, content=json.dumps(_fake_stac_payload(features)).encode())
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        scenes = await client.search_scenes(
            bbox=(0,0,1,1),
            start=datetime(2026,5,13,tzinfo=timezone.utc),
            end=datetime(2026,5,20,tzinfo=timezone.utc),
        )
    assert [s.scene_id for s in scenes] == ["new", "old"]


@pytest.mark.asyncio
async def test_search_scenes_rejects_inverted_window(configured):
    client = CopernicusClient()
    with pytest.raises(ValueError, match="start must be earlier"):
        await client.search_scenes(
            bbox=(0,0,1,1),
            start=datetime(2026,5,20,tzinfo=timezone.utc),
            end=datetime(2026,5,13,tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_search_scenes_surfaces_stac_error(configured):
    transport = _route({
        "openid-connect/token": [
            httpx.Response(200, content=json.dumps(_fake_token_payload()).encode())
        ],
        "catalog/1.0.0/search": [
            httpx.Response(503, content=b"upstream out")
        ],
    })
    async with httpx.AsyncClient(transport=transport) as http:
        client = CopernicusClient(http=http)
        with pytest.raises(CopernicusError, match="CDSE STAC 503"):
            await client.search_scenes(
                bbox=(0,0,1,1),
                start=datetime(2026,5,13,tzinfo=timezone.utc),
                end=datetime(2026,5,20,tzinfo=timezone.utc),
            )


# ─── Parser helpers ────────────────────────────────────────────────────────


def test_extract_mgrs_tile_from_safe_id():
    assert _extract_mgrs_tile(
        "S2A_MSIL2A_20260519T102601_N0512_R022_T31PEN_20260519T181155.SAFE",
        {},
    ) == "31PEN"


def test_extract_mgrs_tile_prefers_explicit_property():
    assert _extract_mgrs_tile("S2A_...", {"s2:mgrs_tile": "33UVR"}) == "33UVR"


def test_extract_mgrs_tile_returns_none_when_unparseable():
    assert _extract_mgrs_tile("NOT-A-SENTINEL-ID", {}) is None


def test_parse_datetime_handles_z_suffix():
    dt = _parse_datetime("2026-05-19T10:28:03.953Z")
    assert dt == datetime(2026, 5, 19, 10, 28, 3, 953000, tzinfo=timezone.utc)


def test_parse_datetime_defaults_to_now_when_missing():
    dt = _parse_datetime(None)
    assert dt.tzinfo is timezone.utc


def test_to_iso_utc_renders_z_suffix():
    assert _to_iso_utc(
        datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    ) == "2026-05-20T12:00:00Z"


def test_parse_feature_handles_missing_optionals():
    scene: SentinelScene = _parse_feature(
        {"id": "minimal-feature", "bbox": [0, 0, 1, 1], "properties": {}},
        collection="sentinel-1-grd",
    )
    assert scene.scene_id == "minimal-feature"
    assert scene.cloud_cover_pct is None
    assert scene.mgrs_tile is None
    assert scene.self_href is None
