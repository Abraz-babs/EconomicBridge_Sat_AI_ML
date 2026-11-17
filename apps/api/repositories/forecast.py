"""Reads for ShockGuard's forecast side. The session's search_path is already
pinned to the request's tenant (db.engine.get_session), so table names are bare.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FORECAST_SOURCE = "ecmwf_forecast_v1"

_FORECAST_COLUMNS = (
    "rain_ifs_mm", "rain_ifs_max_mm", "rain_aifs_mm", "chance_1mm", "chance_10mm",
    "chance_25mm", "chance_50mm", "temp_dawn_c", "temp_afternoon_c",
)


def as_list(value: Any) -> list | None:
    """A JSONB column as a Python list (asyncpg may hand it over as text)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else None


async def latest_forecast(session: AsyncSession) -> list[Mapping[str, Any]]:
    """Every LGA row of the newest stored run, by LGA name. Empty before the first run."""
    rows = (await session.execute(text("""
        SELECT lga, run_at, first_day, cells, rain_ifs_mm, rain_ifs_max_mm, rain_aifs_mm,
               chance_1mm, chance_10mm, chance_25mm, chance_50mm, temp_dawn_c, temp_afternoon_c
          FROM ecmwf_forecast
         WHERE run_at = (SELECT MAX(run_at) FROM ecmwf_forecast)
         ORDER BY lga
    """))).mappings().all()
    return [{**r, **{c: as_list(r[c]) for c in _FORECAST_COLUMNS}} for r in rows]


async def latest_cells(session: AsyncSession) -> Mapping[str, Any] | None:
    """The raw-cell grid of the newest stored run, or None."""
    row = (await session.execute(text("""
        SELECT run_at, lat0, lon0, res, n_rows, n_cols, rain_ifs_mm, rain_aifs_mm, chance_10mm
          FROM ecmwf_forecast_cells
         ORDER BY run_at DESC
         LIMIT 1
    """))).mappings().first()
    if row is None:
        return None
    return {**row, **{c: as_list(row[c]) for c in ("rain_ifs_mm", "rain_aifs_mm", "chance_10mm")}}


async def feed_status(session: AsyncSession, tenant_id: str) -> Mapping[str, Any]:
    """Last success and last run (any outcome) of the forecast feed for this tenant."""
    last = (await session.execute(text("""
        SELECT finished_at, status, error_message
          FROM public.ingestion_runs
         WHERE source = :s AND tenant_id = :t
         ORDER BY finished_at DESC
         LIMIT 1
    """), {"s": FORECAST_SOURCE, "t": tenant_id})).mappings().first()
    ok_at = (await session.execute(text("""
        SELECT MAX(finished_at) FROM public.ingestion_runs
         WHERE source = :s AND tenant_id = :t AND status = 'succeeded'
    """), {"s": FORECAST_SOURCE, "t": tenant_id})).scalar()
    return {
        "last_success_at": ok_at,
        "last_run_at": last["finished_at"] if last else None,
        "last_status": last["status"] if last else None,
        "last_error": last["error_message"] if last else None,
    }
