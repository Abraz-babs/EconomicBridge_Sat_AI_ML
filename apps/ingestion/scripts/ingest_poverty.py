"""CLI entry point for the VIIRS + WorldPop poverty-signal ingest.

Usage (from apps/ingestion/ with the venv active):
    python -m scripts.ingest_poverty

Without an EARTHDATA_TOKEN the VIIRS side returns no granules and the
processor falls back to source='worldpop_v1' (when WorldPop responds) or
source='seed_v1' (when neither catalog returns rows). Either way the
poverty_villages table ends up with one row per (lga, settlement_name,
source) tuple per pilot tenant. Re-runs replace rows for the same tuple.

NEVER point this at a production DB without the runbook checklist:
  - DPA agreement signed for the country
  - migration 0018 applied
  - EARTHDATA_TOKEN sourced from AWS Secrets Manager (not from the env)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from db import get_engine, get_session_factory  # noqa: E402
from tasks.poverty_ingest import ingest_all  # noqa: E402


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    factory = get_session_factory()
    results = await ingest_all(factory)
    total_rows = sum(r.rows_written for r in results)
    print(
        f"poverty.ingest complete — tenants={len(results)} "
        f"rows={total_rows} sources={sorted({s for r in results for s in r.sources_observed})}"
    )
    for r in results:
        print(
            f"  {r.tenant_id:9s}  rows={r.rows_written:>2}  "
            f"viirs={r.viirs_granule_id or '<none>':40s}  "
            f"worldpop={r.worldpop_dataset_id or '<none>'}"
        )
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
