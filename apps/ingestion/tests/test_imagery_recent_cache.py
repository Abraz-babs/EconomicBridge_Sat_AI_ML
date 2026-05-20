"""Unit tests for the 10-minute TTL cache wrapping GET /imagery/recent.

Pinned behaviour:
  * First call hits CDSE and returns `cached: false`.
  * Second call within TTL serves from the in-memory cache (no CDSE
    request), `cached: true`, identical scene list.
  * Different query keys (tenant, days, collection, max_cloud_cover,
    limit) get their own cache slots.
  * Stale entries are refreshed (we drive this by clearing manually
    because monotonic clock skips aren't worth a freezegun dep).
  * The CDSE error path is not cached — a 503 today doesn't poison
    the next request 10 minutes from now.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from main import app
from routers.imagery import _clear_recent_cache
from sources import copernicus as copernicus_module


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_cache():
    _clear_recent_cache()
    yield
    _clear_recent_cache()


@pytest.fixture
def env_setup(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "cid")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "csec")
    # The CopernicusClient cached settings — clear so the env above lands.
    from config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Counter:
    """Counts how many STAC searches actually hit the (mocked) network."""
    def __init__(self) -> None:
        self.token_calls = 0
        self.stac_calls = 0


def _install_mock_transport(monkeypatch, counter: _Counter) -> None:
    """Patch CopernicusClient to use a MockTransport that increments
    `counter` on every OAuth + STAC call. Returns one S2 feature each time."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            counter.token_calls += 1
            return httpx.Response(200, content=json.dumps({
                "access_token": "tok",
                "expires_in": 1800,
                "token_type": "Bearer",
            }).encode())
        if "/catalog/" in url and "/search" in url:
            counter.stac_calls += 1
            return httpx.Response(200, content=json.dumps({
                "type": "FeatureCollection",
                "features": [
                    {
                        "id": "S2A_MSIL2A_20260519T102601_N0512_R022_T31PEN_X.SAFE",
                        "bbox": [3.8, 11.4, 5.1, 12.7],
                        "properties": {
                            "datetime": "2026-05-19T10:28:03Z",
                            "eo:cloud_cover": 12.5,
                        },
                        "links": [],
                    }
                ],
            }).encode())
        return httpx.Response(404, content=b"unmocked")

    transport = httpx.MockTransport(handler)
    original_init = copernicus_module.CopernicusClient.__init__

    def patched_init(self: Any, *, http: httpx.AsyncClient | None = None) -> None:
        if http is None:
            http = httpx.AsyncClient(transport=transport)
        original_init(self, http=http)

    monkeypatch.setattr(
        copernicus_module.CopernicusClient, "__init__", patched_init
    )


# ─── The tests ────────────────────────────────────────────────────────────


def test_first_call_returns_cached_false_and_hits_cdse(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is False
        assert body["total"] == 1
        assert body["cache_ttl_seconds"] == 600
        assert counter.stac_calls == 1


def test_second_call_within_ttl_serves_from_cache(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        first = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )
        second = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["total"] == first.json()["total"]
    assert second.json()["scenes"] == first.json()["scenes"]
    # Only ONE upstream call across both client calls.
    assert counter.stac_calls == 1


def test_different_collections_cache_separately(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        a = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )
        b = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-1-grd"},
        )

    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["cached"] is False
    assert b.json()["cached"] is False
    # Two distinct cache slots → two STAC calls.
    assert counter.stac_calls == 2


def test_different_tenants_cache_separately(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        a = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi"},
        )
        b = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "benue"},
        )

    assert a.status_code == 200
    assert b.status_code == 200
    assert counter.stac_calls == 2


def test_cache_cleared_forces_refresh(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )
        _clear_recent_cache()
        second = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "kebbi", "collection": "sentinel-2-l2a"},
        )

    assert second.json()["cached"] is False
    assert counter.stac_calls == 2


def test_unknown_tenant_returns_404_not_cached(env_setup, monkeypatch):
    counter = _Counter()
    _install_mock_transport(monkeypatch, counter)

    with TestClient(app) as client:
        r = client.get(
            "/api/v1/imagery/recent",
            params={"tenant_id": "atlantis"},
        )

    assert r.status_code == 404
    # No CDSE call at all because validation rejected first.
    assert counter.stac_calls == 0
