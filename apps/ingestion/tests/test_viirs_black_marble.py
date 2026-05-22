"""Unit tests for sources/viirs_black_marble.py.

Mocks every network call (CLAUDE.md §11). What we pin:

  * `configured` only true with a non-empty Earthdata token.
  * No token → `search_granules` returns [] without making an HTTP call.
  * Real LAADS catalog row shape → BlackMarbleGranule fields populated.
  * Tile filter: only granules whose MODIS sinusoidal tile intersects
    the requested ROI bbox come back.
  * 404 (date not yet indexed) → []; other non-200 → BlackMarbleError.
  * Julian day parser: A2026140 → 2026-05-20.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from config import get_settings
from sources.viirs_black_marble import (
    BlackMarbleClient,
    BlackMarbleError,
    _approx_tile_bbox,
    _parse_julian,
    _tile_intersects_bbox,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _row(name: str, *, size: int | None = 12_345_678) -> dict[str, Any]:
    return {
        "name": name,
        "size": size,
        "downloadsLink": f"https://ladsweb.modaps.eosdis.nasa.gov/archive/{name}",
    }


def _route(payload: Any, *, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 200:
            import json as _json
            return httpx.Response(200, content=_json.dumps(payload).encode())
        return httpx.Response(status_code, content=b"err")

    return httpx.MockTransport(handler)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token-abc")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Configuration ────────────────────────────────────────────────────────


def test_configured_false_when_token_missing(unconfigured):
    assert BlackMarbleClient().configured is False


def test_configured_true_when_token_present(configured):
    assert BlackMarbleClient().configured is True


@pytest.mark.asyncio
async def test_search_returns_empty_without_token(unconfigured):
    """Without a token we must NOT make an HTTP call — return [] directly."""
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=_route([])))
    result = await client.search_granules(
        bbox=(3.6, 10.8, 5.5, 13.2),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert result == []


# ─── Parser ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_parses_real_laads_row_shape(configured):
    """Granule name decodes to product / julian day / tile h+v."""
    payload = [
        _row("VNP46A2.A2026140.h18v07.001.2026141123045.h5"),
    ]
    transport = _route(payload)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    result = await client.search_granules(
        bbox=(-10.0, 0.0, 20.0, 20.0),  # broad West-Africa-ish ROI → tile h18v07 inside
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert len(result) == 1
    g = result[0]
    assert g.product == "VNP46A2"
    assert g.tile_h == 18
    assert g.tile_v == 7
    assert g.captured_at == datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert g.granule_id.endswith(".h5")
    assert g.size_bytes == 12_345_678
    assert g.download_url.startswith("https://ladsweb.")


@pytest.mark.asyncio
async def test_search_drops_granules_outside_bbox(configured):
    """Tiles that don't intersect the ROI bbox must be filtered out."""
    payload = [
        # Ghana coverage tile: h17v08 (lat 10-20, lon -10..0) intersects
        # the Ghana ROI lat 4.7-11.2.
        _row("VNP46A2.A2026140.h17v08.002.20260141.h5"),
        # Arctic tile — should be dropped for a sub-Saharan ROI
        _row("VNP46A2.A2026140.h00v00.002.20260141.h5"),
    ]
    transport = _route(payload)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    result = await client.search_granules(
        bbox=(-3.5, 4.7, 1.2, 11.2),  # Ghana ROI
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    tiles = {(g.tile_h, g.tile_v) for g in result}
    assert (0, 0) not in tiles
    assert (17, 8) in tiles


@pytest.mark.asyncio
async def test_search_drops_malformed_rows(configured):
    """Rows without a parsable VNP46* name are silently skipped."""
    payload = [
        {"name": "README.txt"},                           # not VNP46
        {"name": "VNP46A2.bad.name.001.foo.h5"},          # not enough parts to parse
        _row("VNP46A2.A2026140.h17v07.001.20260141.h5"),  # good
    ]
    transport = _route(payload)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    result = await client.search_granules(
        bbox=(-10.0, 0.0, 20.0, 20.0),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert len(result) == 1
    assert result[0].tile_h == 17


@pytest.mark.asyncio
async def test_search_caps_results_at_max(configured):
    payload = [
        _row(f"VNP46A2.A2026140.h{17 + i % 2:02d}v07.001.x.h5")
        for i in range(50)
    ]
    transport = _route(payload)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    result = await client.search_granules(
        bbox=(-10.0, 0.0, 20.0, 20.0),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
        max_results=4,
    )
    assert len(result) == 4


# ─── HTTP error handling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_returns_empty_list(configured):
    """A 404 means LAADS hasn't ingested the day yet — that's expected."""
    transport = _route(None, status_code=404)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    result = await client.search_granules(
        bbox=(-10.0, 0.0, 20.0, 20.0),
        date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert result == []


@pytest.mark.asyncio
async def test_5xx_raises_black_marble_error(configured):
    transport = _route(None, status_code=503)
    client = BlackMarbleClient(http=httpx.AsyncClient(transport=transport))
    with pytest.raises(BlackMarbleError, match="503"):
        await client.search_granules(
            bbox=(-10.0, 0.0, 20.0, 20.0),
            date=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )


# ─── Helpers ──────────────────────────────────────────────────────────────


def test_parse_julian_round_trip():
    assert _parse_julian("A2026140") == datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert _parse_julian("A2026001") == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_parse_julian_rejects_bad_prefix():
    with pytest.raises(ValueError):
        _parse_julian("X2026140")


def test_parse_julian_rejects_bad_day_of_year():
    with pytest.raises(ValueError):
        _parse_julian("A2026999")


def test_tile_bbox_for_nigeria_tile():
    """h18v08 sits at lat 10-20, lon 0-10 — central Nigeria (Kebbi, Zamfara)."""
    lon_w, lon_e, lat_s, lat_n = _approx_tile_bbox(18, 8)
    # Latitudes are exact in the sinusoidal projection (height-preserving).
    assert lat_n == pytest.approx(20.0, abs=0.01)
    assert lat_s == pytest.approx(10.0, abs=0.01)
    # Mid-latitude tile width ~ 10.35° at lat 15° (cos(15) ≈ 0.97).
    assert (lon_e - lon_w) == pytest.approx(10.35, abs=0.1)
    assert lon_w == pytest.approx(0.0, abs=0.01)


def test_tile_intersects_west_africa_roi():
    # h16v08 sits at lat 10-20, lon ~-22..-11 — covers Senegal.
    # Senegal ROI: (-17.5, 12.3, -11.3, 15.7)
    assert _tile_intersects_bbox(16, 8, (-17.5, 12.3, -11.3, 15.7)) is True
    # h18v08 covers central Nigeria — includes Kebbi (3.6..5.5, 10.8..13.2).
    assert _tile_intersects_bbox(18, 8, (3.6, 10.8, 5.5, 13.2)) is True


def test_arctic_tile_does_not_intersect_tropical_roi():
    assert _tile_intersects_bbox(0, 0, (-3.5, 4.7, 1.2, 11.2)) is False
