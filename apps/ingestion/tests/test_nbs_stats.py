"""Tests for sources/nbs_stats.py — Module 06 mobility indicators client.

Pure-function coverage of the mock path + source routing + the
configured/not-configured logic. No DB or HTTP — the mock fallback is
deterministic so we can assert exact ranges and determinism.
"""
from __future__ import annotations

import pytest

from sources.nbs_stats import (
    NIGERIAN_TENANTS,
    SOURCE_ECOWAS,
    SOURCE_NBS,
    NbsStatsClient,
    source_for_tenant,
)


# ─── Source routing ────────────────────────────────────────────────────────


def test_source_for_nigerian_tenants_is_nbs():
    for t in ("kebbi", "fct", "benue", "zamfara"):
        assert source_for_tenant(t) == SOURCE_NBS


def test_source_for_ecowas_tenants_is_ecowas_stat():
    for t in ("ghana", "senegal"):
        assert source_for_tenant(t) == SOURCE_ECOWAS


def test_nigerian_tenants_set_excludes_ecowas():
    assert "ghana" not in NIGERIAN_TENANTS
    assert "senegal" not in NIGERIAN_TENANTS
    assert "kebbi" in NIGERIAN_TENANTS


# ─── configured_for ────────────────────────────────────────────────────────


def test_configured_for_is_false_without_keys():
    """Default settings have empty keys → mock mode for all tenants."""
    client = NbsStatsClient()
    assert client.configured_for("kebbi") is False
    assert client.configured_for("ghana") is False


# ─── Mock indicators ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_one_indicator_per_lga():
    client = NbsStatsClient()
    lgas = ["Argungu", "Birnin Kebbi", "Zuru"]
    out = await client.fetch_indicators("kebbi", lgas)
    assert [i.lga for i in out] == lgas


@pytest.mark.asyncio
async def test_mock_values_are_in_valid_ranges():
    client = NbsStatsClient()
    out = await client.fetch_indicators("fct", ["Abaji", "Bwari", "AMAC"])
    for ind in out:
        assert 0.0 <= ind.cost_of_living_index <= 300.0
        assert ind.avg_household_income_ngn >= 0
        assert 0.0 <= ind.income_opportunity_score <= 1.0
        assert 0.0 <= ind.displacement_capacity_index <= 1.0
        assert ind.population > 0


@pytest.mark.asyncio
async def test_mock_tags_source_per_tenant():
    client = NbsStatsClient()
    ng = await client.fetch_indicators("kebbi", ["Argungu"])
    ecowas = await client.fetch_indicators("ghana", ["Tamale"])
    assert ng[0].source == SOURCE_NBS
    assert ecowas[0].source == SOURCE_ECOWAS


@pytest.mark.asyncio
async def test_mock_is_deterministic():
    client = NbsStatsClient()
    a = await client.fetch_indicators("kebbi", ["Argungu", "Jega"])
    b = await client.fetch_indicators("kebbi", ["Argungu", "Jega"])
    assert a == b


@pytest.mark.asyncio
async def test_mock_differs_from_seed_salt():
    """The live mock uses a 'live_col' salt distinct from the seed
    script's 'col' salt, so nbs_col_v1 values aren't identical to
    seed_v1 — the dashboard shows a real difference on swap-in.

    We can't import the seed script here (different package), so assert
    the weaker invariant: two different LGAs produce different COL
    values (proves the hash actually varies per input)."""
    client = NbsStatsClient()
    out = await client.fetch_indicators("kebbi", ["Argungu", "Yauri"])
    assert out[0].cost_of_living_index != out[1].cost_of_living_index


@pytest.mark.asyncio
async def test_fetch_raises_when_configured_but_unimplemented(monkeypatch):
    """If a key IS set, the client must NOT silently return mock data —
    it raises NotImplementedError until the real HTTP path is built."""
    client = NbsStatsClient()
    monkeypatch.setattr(client._settings, "nbs_api_key", "fake-key")
    with pytest.raises(NotImplementedError):
        await client.fetch_indicators("kebbi", ["Argungu"])
