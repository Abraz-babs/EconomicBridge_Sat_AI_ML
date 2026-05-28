"""Tests for sources/giga_itu_stats.py — Module 07 SkillsBridge client.

Pure-function coverage of the mock path + configured logic. No DB or
HTTP — the mock fallback is deterministic.
"""
from __future__ import annotations

import pytest

from sources.giga_itu_stats import (
    SOURCE_GIGA,
    GigaItuStatsClient,
)


def test_source_constant_is_giga_v1():
    assert SOURCE_GIGA == "giga_v1"


def test_configured_is_false_without_keys():
    assert GigaItuStatsClient().configured is False


@pytest.mark.asyncio
async def test_fetch_returns_one_indicator_per_lga():
    client = GigaItuStatsClient()
    lgas = ["Argungu", "Birnin Kebbi", "Zuru"]
    out = await client.fetch_indicators("kebbi", lgas)
    assert [i.lga for i in out] == lgas


@pytest.mark.asyncio
async def test_mock_values_are_in_valid_ranges():
    client = GigaItuStatsClient()
    out = await client.fetch_indicators("fct", ["Abaji", "Bwari", "AMAC"])
    for ind in out:
        assert 0.0 <= ind.internet_coverage_pct <= 100.0
        assert 0.0 <= ind.mobile_coverage_pct <= 100.0
        assert 0.0 <= ind.electricity_reliability <= 1.0
        assert 0.0 <= ind.learning_gap_index <= 1.0
        assert ind.school_count >= 1
        assert ind.school_density_per_10k > 0
        assert ind.youth_population > 0
        assert ind.source == SOURCE_GIGA


@pytest.mark.asyncio
async def test_mock_mobile_runs_at_or_above_internet():
    """ITU's 2G blanket is wider than internet — same invariant the seed
    script holds."""
    client = GigaItuStatsClient()
    for ind in await client.fetch_indicators("kebbi", ["Argungu", "Jega"]):
        assert ind.mobile_coverage_pct >= ind.internet_coverage_pct


@pytest.mark.asyncio
async def test_mock_is_deterministic():
    client = GigaItuStatsClient()
    a = await client.fetch_indicators("ghana", ["Tamale", "Wa"])
    b = await client.fetch_indicators("ghana", ["Tamale", "Wa"])
    assert a == b


@pytest.mark.asyncio
async def test_fct_has_better_connectivity_than_kebbi():
    """Capital region anchors higher than rural north — sanity that the
    per-tenant profile is actually applied."""
    client = GigaItuStatsClient()
    fct = await client.fetch_indicators("fct", ["Abaji", "Bwari", "AMAC"])
    kebbi = await client.fetch_indicators("kebbi", ["Argungu", "Jega", "Zuru"])
    fct_mean = sum(i.internet_coverage_pct for i in fct) / len(fct)
    kebbi_mean = sum(i.internet_coverage_pct for i in kebbi) / len(kebbi)
    assert fct_mean > kebbi_mean


@pytest.mark.asyncio
async def test_fetch_raises_when_configured_but_unimplemented(monkeypatch):
    client = GigaItuStatsClient()
    monkeypatch.setattr(client._settings, "giga_api_key", "fake-key")
    with pytest.raises(NotImplementedError):
        await client.fetch_indicators("kebbi", ["Argungu"])
