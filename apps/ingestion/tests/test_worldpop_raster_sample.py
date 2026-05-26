"""Tests for tasks/worldpop_raster_sample.py — Slice 09 / Phase B.

* URL builder + ISO3 map: pure functions, exhaustive coverage.
* sweep_tenant orchestration: stub AsyncSession + monkeypatch
  `sample_points` so the test never touches WorldPop's CDN or the
  real database. We verify:
    - empty village list → SweepResult(requested=0, valid=0)
    - sampler raises CogSamplerError → SweepResult(failed=True)
    - mix of valid + nodata samples → counts split correctly
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sources.cog_sampler import CogSample, CogSamplerError
from tasks import worldpop_raster_sample as wp
from tasks.worldpop_raster_sample import (
    SOURCE_NAME,
    TENANT_TO_ISO3,
    sweep_tenant,
    worldpop_url_for,
)


# ─── Pure helpers ─────────────────────────────────────────────────────────


def test_source_name_is_worldpop_ppp_v1():
    assert SOURCE_NAME == "worldpop_ppp_v1"


def test_worldpop_url_uppercases_iso3_in_path():
    url = worldpop_url_for("nga")
    assert "/NGA/" in url
    assert url.endswith("/nga_ppp_2020.tif")


def test_worldpop_url_honours_year_override():
    url = worldpop_url_for("GHA", year=2018)
    assert "/2018/GHA/" in url
    assert url.endswith("/gha_ppp_2018.tif")


def test_every_pilot_tenant_has_iso3_mapping():
    expected = {
        "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
        "fct", "ghana", "senegal", "nasarawa",
    }
    assert expected <= set(TENANT_TO_ISO3)


def test_nigerian_pilots_share_nga_iso3():
    for slug in ("kebbi", "benue", "plateau", "kaduna",
                 "niger", "zamfara", "nasarawa", "fct"):
        assert TENANT_TO_ISO3[slug] == "NGA", f"{slug} drifted from NGA"


# ─── sweep_tenant orchestration ───────────────────────────────────────────


def _mk_session(village_rows: list[dict[str, Any]]) -> MagicMock:
    """Build a stub AsyncSession that returns village_rows from the first
    .execute() (the SELECT), and accepts every subsequent .execute() (the
    upsert INSERTs) plus commit()."""
    session = MagicMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = village_rows
    upsert_result = MagicMock()

    # First call returns the SELECT result, all later calls return a no-op
    # (the upsert insert).
    session.execute = AsyncMock(side_effect=[
        # _load_villages does SET search_path first then SELECT — set_tenant_schema
        # is a separate call so we need a no-op for it too.
        MagicMock(),       # SET search_path (from set_tenant_schema)
        select_result,     # SELECT poverty_villages
        MagicMock(),       # SET search_path (from _upsert_samples)
        *[upsert_result] * len(village_rows),
    ])
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_sweep_tenant_no_villages_returns_zero_requested():
    session = _mk_session([])
    result = await sweep_tenant(session, "kebbi")
    assert result.tenant_id == "kebbi"
    assert result.requested == 0
    assert result.valid == 0
    assert result.failed is False


@pytest.mark.asyncio
async def test_sweep_tenant_unknown_tenant_without_url_returns_failed():
    session = _mk_session([])
    result = await sweep_tenant(session, "atlantis")
    assert result.failed is True
    assert "no WorldPop ISO3 mapping" in (result.error or "")


@pytest.mark.asyncio
async def test_sweep_tenant_sampler_failure_is_propagated(monkeypatch):
    village_rows = [
        {"settlement_name": "Argungu settlement 1", "lon": 4.52, "lat": 12.74},
    ]
    session = _mk_session(village_rows)

    def boom(*_args, **_kwargs):
        raise CogSamplerError("network blew up")
    monkeypatch.setattr(wp, "sample_points", boom)

    result = await sweep_tenant(session, "kebbi")
    assert result.failed is True
    assert result.requested == 1
    assert result.valid == 0
    assert "network blew up" in (result.error or "")


@pytest.mark.asyncio
async def test_sweep_tenant_counts_valid_and_nodata(monkeypatch):
    rows = [
        {"settlement_name": f"Argungu settlement {i}", "lon": 4.52, "lat": 12.74}
        for i in range(1, 4)
    ]
    session = _mk_session(rows)

    samples = [
        CogSample(lon=4.52, lat=12.74, value=100.0, valid=True, band=1),
        CogSample(lon=4.52, lat=12.74, value=None, valid=False, band=1),
        CogSample(lon=4.52, lat=12.74, value=200.0, valid=True, band=1),
    ]

    async def fake_to_thread(_fn, *_args, **_kwargs):
        return samples
    monkeypatch.setattr(wp.asyncio, "to_thread", fake_to_thread)

    result = await sweep_tenant(session, "kebbi")
    assert result.failed is False
    assert result.requested == 3
    assert result.valid == 2
    assert result.nodata == 1
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_tenant_url_override_bypasses_iso3_check(monkeypatch):
    """`--url <local>` flow: we hand the sampler a local path even for
    unknown tenants. Useful for smoke tests against synthetic COGs."""
    rows = [
        {"settlement_name": "AMAC settlement 1", "lon": 7.48, "lat": 9.07},
    ]
    session = _mk_session(rows)

    async def fake_to_thread(_fn, *_args, **_kwargs):
        return [CogSample(lon=7.48, lat=9.07, value=42.0, valid=True, band=1)]
    monkeypatch.setattr(wp.asyncio, "to_thread", fake_to_thread)

    result = await sweep_tenant(
        session, "fct", url_override="C:/tmp/whatever.tif",
    )
    assert result.failed is False
    assert result.valid == 1
