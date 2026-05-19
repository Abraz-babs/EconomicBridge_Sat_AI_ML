"""Unit tests for sources/n2yo.py + routers/passes.py.

Real N2YO calls are mocked via a tiny in-memory transport so we never
hit the network in CI (CLAUDE.md §11 — satellite APIs always mocked
in tests).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from config import get_settings
from sources.n2yo import (
    SATELLITE_CATALOG,
    N2yoClient,
    N2yoError,
    _utc_from_epoch,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


def _fake_payload(*, satid: int = 39634, satname: str = "SENTINEL 1A") -> dict:
    """One info block + two passes — enough to exercise the parser."""
    return {
        "info": {
            "satid": satid,
            "satname": satname,
            "transactionscount": 1,
            "passescount": 2,
        },
        "passes": [
            {
                "startAz": 6.79, "startAzCompass": "N", "startEl": 0,
                "startUTC": 1747728620,
                "maxAz": 90.4, "maxAzCompass": "E", "maxEl": 73.6,
                "maxUTC": 1747729200,
                "endAz": 174.0, "endAzCompass": "S", "endEl": 0,
                "endUTC": 1747729780,
                "duration": 1160,
            },
            {
                "startAz": 12.0, "startAzCompass": "N", "startEl": 0,
                "startUTC": 1747815020,
                "maxAz": 80.0, "maxAzCompass": "E", "maxEl": 41.0,
                "maxUTC": 1747815620,
                "endAz": 150.0, "endAzCompass": "SE", "endEl": 0,
                "endUTC": 1747816220,
                "duration": 1200,
            },
        ],
    }


def _mock_transport(payload: dict, status: int = 200) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=json.dumps(payload).encode())
    return httpx.MockTransport(handler)


@pytest.fixture
def configured_key(monkeypatch):
    """Ensure N2YO_API_KEY is non-empty so .configured returns True."""
    monkeypatch.setenv("N2YO_API_KEY", "test-key-1234")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Catalogue ─────────────────────────────────────────────────────────────


def test_catalog_includes_expected_satellites():
    expected = {"SENTINEL-1A", "SENTINEL-2A", "SENTINEL-2B", "TERRA", "AQUA"}
    assert expected.issubset(SATELLITE_CATALOG)


def test_catalog_groups_are_canonical():
    groups = {grp for _, grp in SATELLITE_CATALOG.values()}
    assert groups == {"S1", "S2", "VIIRS", "MODIS"}


def test_terra_norad_id_is_25994_not_iss():
    # Regression: 25544 is the ISS. Terra is 25994. Bug caught during
    # Phase A.2 build — the test pins it so we don't slip again.
    norad_id, _ = SATELLITE_CATALOG["TERRA"]
    assert norad_id == 25994


# ─── Client behaviour ──────────────────────────────────────────────────────


def test_client_reports_unconfigured_when_key_empty(monkeypatch):
    monkeypatch.setenv("N2YO_API_KEY", "")
    get_settings.cache_clear()
    try:
        client = N2yoClient()
        assert client.configured is False
    finally:
        get_settings.cache_clear()


def test_client_reports_configured_when_key_set(configured_key):
    assert N2yoClient().configured is True


@pytest.mark.asyncio
async def test_fetch_passes_raises_when_unconfigured(monkeypatch):
    monkeypatch.setenv("N2YO_API_KEY", "")
    get_settings.cache_clear()
    try:
        client = N2yoClient()
        with pytest.raises(N2yoError, match="not configured"):
            await client.fetch_passes(
                satellite_key="SENTINEL-1A",
                observer_lat=12.0,
                observer_lon=4.5,
            )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fetch_passes_rejects_unknown_satellite(configured_key):
    client = N2yoClient()
    with pytest.raises(ValueError, match="Unknown satellite"):
        await client.fetch_passes(
            satellite_key="NOT-A-SAT",
            observer_lat=12.0, observer_lon=4.5,
        )


@pytest.mark.asyncio
async def test_fetch_passes_rejects_out_of_range_days(configured_key):
    client = N2yoClient()
    with pytest.raises(ValueError, match="days must be 1..10"):
        await client.fetch_passes(
            satellite_key="SENTINEL-1A",
            observer_lat=12.0, observer_lon=4.5,
            days=11,
        )


@pytest.mark.asyncio
async def test_fetch_passes_rejects_out_of_range_elevation(configured_key):
    client = N2yoClient()
    with pytest.raises(ValueError, match="min_elevation"):
        await client.fetch_passes(
            satellite_key="SENTINEL-1A",
            observer_lat=12.0, observer_lon=4.5,
            min_elevation=0,
        )


@pytest.mark.asyncio
async def test_fetch_passes_parses_payload(configured_key):
    transport = _mock_transport(_fake_payload())
    async with httpx.AsyncClient(transport=transport) as http:
        client = N2yoClient(http=http)
        passes = await client.fetch_passes(
            satellite_key="SENTINEL-1A",
            observer_lat=12.0, observer_lon=4.5,
        )

    assert len(passes) == 2
    p = passes[0]
    assert p.satellite_name == "SENTINEL-1A"
    assert p.satellite_group == "S1"
    assert p.norad_id == 39634
    assert p.observer_lat == 12.0 and p.observer_lon == 4.5
    assert p.max_elevation_deg == 73.6
    assert p.max_azimuth_compass == "E"
    assert p.duration_seconds == 1160
    # UTC timestamps round-trip correctly.
    assert p.start_utc == _utc_from_epoch(1747728620)
    assert p.start_utc.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_fetch_passes_returns_empty_when_no_passes(configured_key):
    transport = _mock_transport({"info": {"passescount": 0}})
    async with httpx.AsyncClient(transport=transport) as http:
        client = N2yoClient(http=http)
        passes = await client.fetch_passes(
            satellite_key="SENTINEL-1A",
            observer_lat=12.0, observer_lon=4.5,
        )
    assert passes == []


@pytest.mark.asyncio
async def test_fetch_passes_surfaces_n2yo_error_field(configured_key):
    transport = _mock_transport({"error": "Invalid api key."})
    async with httpx.AsyncClient(transport=transport) as http:
        client = N2yoClient(http=http)
        with pytest.raises(N2yoError, match="Invalid api key"):
            await client.fetch_passes(
                satellite_key="SENTINEL-1A",
                observer_lat=12.0, observer_lon=4.5,
            )


@pytest.mark.asyncio
async def test_fetch_passes_surfaces_http_error(configured_key):
    transport = _mock_transport({}, status=500)
    async with httpx.AsyncClient(transport=transport) as http:
        client = N2yoClient(http=http)
        with pytest.raises(N2yoError, match="N2YO 500"):
            await client.fetch_passes(
                satellite_key="SENTINEL-1A",
                observer_lat=12.0, observer_lon=4.5,
            )


@pytest.mark.asyncio
async def test_duration_derived_from_timestamps_when_field_missing(configured_key):
    # N2YO's radiopasses endpoint omits `duration`; we derive it from
    # endUTC - startUTC. Regression test for that fix.
    payload = _fake_payload()
    for p in payload["passes"]:
        p.pop("duration", None)
    transport = _mock_transport(payload)
    async with httpx.AsyncClient(transport=transport) as http:
        client = N2yoClient(http=http)
        passes = await client.fetch_passes(
            satellite_key="SENTINEL-1A",
            observer_lat=12.0, observer_lon=4.5,
        )
    # endUTC - startUTC for the first fixture pass = 1747729780 - 1747728620.
    assert passes[0].duration_seconds == 1747729780 - 1747728620


def test_utc_from_epoch_returns_aware_datetime():
    dt = _utc_from_epoch(1747728620)
    assert dt == datetime(2025, 5, 20, 8, 10, 20, tzinfo=timezone.utc)
    assert dt.tzinfo is timezone.utc
