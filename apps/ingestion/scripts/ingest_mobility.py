"""Manual mobility (NBS / ECOWAS STAT) ingest — Module 06.

Usage (from apps/ingestion/, venv active):
    python -m scripts.ingest_mobility              # all pilots
    python -m scripts.ingest_mobility kebbi fct    # subset

With no NBS_API_KEY / ECOWAS_STAT_API_KEY set, the client returns
deterministic mock indicators tagged nbs_col_v1 / ecowas_stat_v1 so
the seed→live swap-in is demonstrable without credentials. Idempotent:
each (tenant, lga, source) cell is upserted via the UNIQUE constraint.

NEVER run against a non-dev DB; the production cadence (NBS publishes
CPI monthly) belongs in the scheduler once the live API is wired.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from db import PILOT_TENANT_IDS, get_engine, get_session_factory  # noqa: E402
from tasks.mobility_ingest import ingest_mobility_for_tenant  # noqa: E402


async def main() -> int:
    tenant_ids = sys.argv[1:] or sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    rc = 0
    async with factory() as session:
        for tid in tenant_ids:
            try:
                result = await ingest_mobility_for_tenant(session, tenant_id=tid)
            except Exception as exc:  # noqa: BLE001
                print(f"  {tid:<10}  FAILED  {exc}", file=sys.stderr)
                rc = 1
                continue
            mode = "mock" if result.mock else "live"
            print(
                f"  {tid:<10}  ok  {result.rows_upserted}/{result.lgas_found} "
                f"rows -> {result.source} ({mode})"
            )
    await get_engine().dispose()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
