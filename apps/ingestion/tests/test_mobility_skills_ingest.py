"""Task-level tests for mobility_ingest + skills_ingest (Slices 21/22).

Mock the AsyncSession so the orchestration (read seed LGAs → fetch
indicators → upsert → commit) is covered without a live DB. Mirrors
the worldpop_raster_sample test pattern.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tasks.mobility_ingest import ingest_mobility_for_tenant
from tasks.skills_ingest import ingest_skills_for_tenant


def _session_with_seed_lgas(rows: list[dict[str, Any]]) -> MagicMock:
    """Stub AsyncSession: first SELECT (after a SET) returns `rows`;
    every later execute (SET + INSERTs) is a no-op; commit awaited."""
    session = MagicMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = rows
    # Call order in the task:
    #   set_tenant_schema → SET (no-op)
    #   _seed_lgas SELECT → select_result
    #   set_tenant_schema → SET (no-op)
    #   N × INSERT → no-op
    session.execute = AsyncMock(side_effect=[
        MagicMock(),       # SET (set_tenant_schema in _seed_lgas)
        select_result,     # SELECT seed rows
        MagicMock(),       # SET (set_tenant_schema before upserts)
        *[MagicMock()] * 64,  # generous slack for per-LGA INSERTs
    ])
    session.commit = AsyncMock()
    return session


_SEED_ROWS = [
    {"lga": "Argungu", "lon": 4.52, "lat": 12.74},
    {"lga": "Jega", "lon": 4.38, "lat": 12.22},
]


# ─── mobility_ingest ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mobility_ingest_upserts_one_row_per_seed_lga():
    session = _session_with_seed_lgas(_SEED_ROWS)
    result = await ingest_mobility_for_tenant(session, tenant_id="kebbi")
    assert result.lgas_found == 2
    assert result.rows_upserted == 2
    assert result.source == "nbs_col_v1"
    assert result.mock is True
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_mobility_ingest_no_seed_rows_is_a_noop():
    session = _session_with_seed_lgas([])
    result = await ingest_mobility_for_tenant(session, tenant_id="kebbi")
    assert result.lgas_found == 0
    assert result.rows_upserted == 0


@pytest.mark.asyncio
async def test_mobility_ingest_ecowas_source_for_ghana():
    session = _session_with_seed_lgas([{"lga": "Tamale", "lon": -0.84, "lat": 9.4}])
    result = await ingest_mobility_for_tenant(session, tenant_id="ghana")
    assert result.source == "ecowas_stat_v1"


# ─── skills_ingest ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skills_ingest_upserts_one_row_per_seed_lga():
    session = _session_with_seed_lgas(_SEED_ROWS)
    result = await ingest_skills_for_tenant(session, tenant_id="kebbi")
    assert result.lgas_found == 2
    assert result.rows_upserted == 2
    assert result.source == "giga_v1"
    assert result.mock is True
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_skills_ingest_no_seed_rows_is_a_noop():
    session = _session_with_seed_lgas([])
    result = await ingest_skills_for_tenant(session, tenant_id="fct")
    assert result.lgas_found == 0
    assert result.rows_upserted == 0
