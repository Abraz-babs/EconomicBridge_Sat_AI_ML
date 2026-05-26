"""Manual WorldPop raster sweep (Slice 09 / Phase B).

Usage (from apps/ingestion/, venv active):
    python -m scripts.ingest_worldpop_samples                    # all pilots
    python -m scripts.ingest_worldpop_samples kebbi fct          # subset
    python -m scripts.ingest_worldpop_samples --url <file>  fct  # local COG

The CLI just calls `tasks.worldpop_raster_sample.sweep_tenant` per
tenant and prints a one-line summary. Idempotent: each (tenant, lga,
source, year) cell is upserted via the functional UNIQUE INDEX in
migration 0024 so a re-run never duplicates.

NEVER run against a non-dev DB; the scheduler in main.py owns the
production cadence (daily 07:00 UTC, after VIIRS catalog at 06:30).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from db import PILOT_TENANT_IDS, get_engine, get_session_factory  # noqa: E402
from tasks.worldpop_raster_sample import sweep_tenant  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "tenants", nargs="*",
        help="Tenant slugs to sweep. Empty = every pilot tenant.",
    )
    p.add_argument(
        "--url", default=None,
        help="Override the WorldPop URL (useful for local-COG smoke tests). "
             "Requires exactly one tenant slug.",
    )
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    tenant_ids = args.tenants or sorted(PILOT_TENANT_IDS)

    if args.url and len(tenant_ids) != 1:
        print("--url requires exactly one tenant slug", file=sys.stderr)
        return 2

    factory = get_session_factory()
    rc = 0
    async with factory() as session:
        for tid in tenant_ids:
            result = await sweep_tenant(
                session, tid, url_override=args.url,
            )
            if result.failed:
                print(
                    f"  {tid:<10}  FAILED  {result.error}",
                    file=sys.stderr,
                )
                rc = 1
            else:
                print(
                    f"  {tid:<10}  ok      "
                    f"{result.valid}/{result.requested} valid, "
                    f"{result.nodata} nodata"
                )

    engine = get_engine()
    await engine.dispose()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
