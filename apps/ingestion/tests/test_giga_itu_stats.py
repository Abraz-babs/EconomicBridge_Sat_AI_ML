"""Tests for sources/giga_itu_stats.py — Module 07 SkillsBridge client.

Mock path is deterministic (no DB/HTTP). The real path is exercised with a
stubbed GIGA schools_location response (httpx.MockTransport) — no live key.
The autouse conftest fixture forces giga_api_key empty by default; tests that
want the real/configured path set it locally via monkeypatch.
"""
from __future__ import annotations

import json

import httpx
import pytest

from sources.giga_itu_stats import (
    SOURCE_GIGA,
    GigaItuStatsClient,
    _nearest_lga,
)


def _coords(names: list[str]) -> dict[str, tuple[float, float]]:
    """LGA name → dummy (lon, lat) centroid for mock-path tests."""
    return {n: (4.0 + i * 0.1, 12.0) for i, n in enumerate(names)}


# ─── config / helpers ──────────────────────────────────────────────────────


def test_source_constant_is_giga_v1():
    assert SOURCE_GIGA == "giga_v1"


def test_configured_false_without_key():
    assert GigaItuStatsClient().configured is False  # autouse fixture empties it


def test_configured_true_with_key(monkeypatch):
    c = GigaItuStatsClient()
    monkeypatch.setattr(c._settings, "giga_api_key", "k")
    assert c.configured is True


def test_nearest_lga_respects_radius():
    coords = {"Argungu": (4.52, 12.74), "Jega": (4.38, 12.22)}
    assert _nearest_lga(4.50, 12.70, coords) == "Argungu"
    assert _nearest_lga(4.40, 12.25, coords) == "Jega"
    # 10° away → beyond the bin radius → unattributed
    assert _nearest_lga(20.0, 20.0, coords) is None


# ─── mock path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_one_indicator_per_lga():
    lgas = ["Argungu", "Birnin Kebbi", "Zuru"]
    out = await GigaItuStatsClient().fetch_indicators("kebbi", _coords(lgas))
    assert [i.lga for i in out] == lgas


@pytest.mark.asyncio
async def test_mock_values_are_in_valid_ranges():
    out = await GigaItuStatsClient().fetch_indicators("fct", _coords(["Abaji", "Bwari", "AMAC"]))
    for ind in out:
        assert 0.0 <= ind.internet_coverage_pct <= 100.0
        assert 0.0 <= ind.mobile_coverage_pct <= 100.0
        assert 0.0 <= ind.electricity_reliability <= 1.0
        assert 0.0 <= ind.learning_gap_index <= 1.0
        assert ind.school_count >= 1
        assert ind.school_density_per_10k > 0
        assert ind.source == SOURCE_GIGA


@pytest.mark.asyncio
async def test_mock_is_deterministic():
    a = await GigaItuStatsClient().fetch_indicators("ghana", _coords(["Tamale", "Wa"]))
    b = await GigaItuStatsClient().fetch_indicators("ghana", _coords(["Tamale", "Wa"]))
    assert a == b


# ─── real path (stubbed GIGA HTTP) ─────────────────────────────────────────


def _giga_transport(schools: list[dict]) -> httpx.MockTransport:
    body = {"success": True, "timestamp": "2026-05-30T00:00:00Z", "data": schools}
    return httpx.MockTransport(
        lambda req: httpx.Response(200, content=json.dumps(body).encode())
    )


@pytest.mark.asyncio
async def test_real_bins_schools_to_nearest_lga(monkeypatch):
    """Real GIGA school points are counted into the nearest LGA (within radius);
    far-away points are dropped; connectivity stays modelled."""
    GigaItuStatsClient._schools_cache.clear()
    schools = [
        {"longitude": 4.52, "latitude": 12.74},  # Argungu
        {"longitude": 4.53, "latitude": 12.73},  # Argungu
        {"longitude": 4.38, "latitude": 12.22},  # Jega
        {"longitude": 20.0, "latitude": 20.0},   # far away → dropped
    ]
    client = GigaItuStatsClient(http=httpx.AsyncClient(transport=_giga_transport(schools)))
    monkeypatch.setattr(client._settings, "giga_api_key", "live-key")
    coords = {"Argungu": (4.52, 12.74), "Jega": (4.38, 12.22)}

    out = await client.fetch_indicators("kebbi", coords)
    by_lga = {i.lga: i for i in out}
    assert by_lga["Argungu"].school_count == 2
    assert by_lga["Jega"].school_count == 1
    assert all(i.source == SOURCE_GIGA for i in out)
    # connectivity is still modelled (present + in range), not zero
    assert all(0.0 <= i.internet_coverage_pct <= 100.0 for i in out)
    GigaItuStatsClient._schools_cache.clear()


@pytest.mark.asyncio
async def test_real_connectivity_anchored_to_wb_national(monkeypatch):
    """When World Bank national ICT figures are supplied, per-LGA internet sits
    near the national rate (±spread), not the mock anchor."""
    GigaItuStatsClient._schools_cache.clear()
    schools = [{"longitude": 4.52, "latitude": 12.74}]
    client = GigaItuStatsClient(http=httpx.AsyncClient(transport=_giga_transport(schools)))
    monkeypatch.setattr(client._settings, "giga_api_key", "live-key")
    out = await client.fetch_indicators(
        "kebbi", {"Argungu": (4.52, 12.74), "Jega": (4.38, 12.22)},
        national_internet_pct=41.0, national_mobile_pct=71.0,
    )
    for i in out:
        assert abs(i.internet_coverage_pct - 41.0) <= 6.0  # within ±spread of WB
        assert i.mobile_coverage_pct >= i.internet_coverage_pct
    GigaItuStatsClient._schools_cache.clear()


@pytest.mark.asyncio
async def test_real_non_200_raises(monkeypatch):
    from sources.giga_itu_stats import GigaItuStatsError
    GigaItuStatsClient._schools_cache.clear()
    transport = httpx.MockTransport(lambda req: httpx.Response(403, content=b"{}"))
    client = GigaItuStatsClient(http=httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(client._settings, "giga_api_key", "live-key")
    with pytest.raises(GigaItuStatsError):
        await client.fetch_indicators("kebbi", {"Argungu": (4.52, 12.74)})
    GigaItuStatsClient._schools_cache.clear()
