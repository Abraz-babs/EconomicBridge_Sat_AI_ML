"""Reads for the forecast check. The session's search_path is already pinned to
the request's tenant (db.engine.get_session), so table names are bare.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CHECK_SOURCE = "forecast_check_v1"
MEASURED_PRODUCT = "GPM_3IMERGDL.07"
LEADS = 15
CHANCE_LEADS = 10


async def latest_summary(session: AsyncSession) -> Mapping[str, Any] | None:
    """The newest stored scorecard, or None before the first one."""
    row = (await session.execute(text("""
        SELECT summary, created_at
          FROM forecast_check_summary
         ORDER BY created_at DESC
         LIMIT 1
    """))).mappings().first()
    if row is None:
        return None
    summary = row["summary"]
    if isinstance(summary, str):
        summary = json.loads(summary)
    return {"summary": summary, "created_at": row["created_at"]}


async def newest_measured_day(session: AsyncSession) -> date | None:
    """The most recent day IMERG has been measured for."""
    return (await session.execute(text(
        "SELECT MAX(day) FROM rain_measured_daily WHERE product = :p"), {"p": MEASURED_PRODUCT})).scalar()


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


async def check_day(session: AsyncSession, day: date) -> list[dict[str, Any]]:
    """Every LGA measured on `day`, with the forecast for that day from each run
    made 0..14 days before it (00 UTC runs; None where no run is stored)."""
    rows = (await session.execute(text("""
        SELECT m.lga, m.rain_mm, m.rain_max_mm, m.wet_share_1mm, m.wet_share_10mm,
               (m.day - f.first_day)                    AS lead,
               f.rain_ifs_mm  ->> (m.day - f.first_day) AS ifs,
               f.rain_aifs_mm ->> (m.day - f.first_day) AS aifs,
               f.chance_1mm   ->> (m.day - f.first_day) AS p1,
               f.chance_10mm  ->> (m.day - f.first_day) AS p10
          FROM rain_measured_daily m
          LEFT JOIN ecmwf_forecast f
            ON f.lga = m.lga
           AND f.first_day BETWEEN m.day - 14 AND m.day
           AND EXTRACT(HOUR FROM f.run_at AT TIME ZONE 'UTC') = 0
         WHERE m.day = :day AND m.product = :p
         ORDER BY m.lga
    """), {"day": day, "p": MEASURED_PRODUCT})).mappings().all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = out.setdefault(r["lga"], {
            "lga": r["lga"], "measured_mm": r["rain_mm"], "measured_max_mm": r["rain_max_mm"],
            "wet_share_1mm": r["wet_share_1mm"], "wet_share_10mm": r["wet_share_10mm"],
            "ifs_mm": [None] * LEADS, "aifs_mm": [None] * LEADS,
            "chance_1mm": [None] * CHANCE_LEADS, "chance_10mm": [None] * CHANCE_LEADS,
        })
        k = r["lead"]
        if k is None or not 0 <= k < LEADS:
            continue
        a["ifs_mm"][k], a["aifs_mm"][k] = _num(r["ifs"]), _num(r["aifs"])
        if k < CHANCE_LEADS:
            a["chance_1mm"][k], a["chance_10mm"][k] = _num(r["p1"]), _num(r["p10"])
    return list(out.values())
