"""Manual SkillsBridge (GIGA / ITU) ingest — Module 07.

Usage (from apps/ingestion/, venv active):
    python -m scripts.ingest_skills              # all pilots
    python -m scripts.ingest_skills kebbi fct    # subset

With no GIGA_API_KEY / ITU_API_KEY set, the client returns
deterministic mock indicators tagged giga_v1 so the seed->live swap-in
is demonstrable without credentials. Idempotent via UNIQUE
(tenant, lga, source).

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from db import PILOT_TENANT_IDS, get_engine, get_session_factory  # noqa: E402
from tasks.skills_ingest import ingest_skills_for_tenant  # noqa: E402


async def main() -> int:
    tenant_ids = sys.argv[1:] or sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    rc = 0
    async with factory() as session:
        for tid in tenant_ids:
            try:
                result = await ingest_skills_for_tenant(session, tenant_id=tid)
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
