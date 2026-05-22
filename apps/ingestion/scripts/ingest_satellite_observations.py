"""CLI entry point for the Sentinel-1 + Sentinel-2 Statistical-API ingest.

Usage (from apps/ingestion/ with the venv active):
    python -m scripts.ingest_satellite_observations
    python -m scripts.ingest_satellite_observations --tenant kebbi
    python -m scripts.ingest_satellite_observations --tenants kebbi,ghana

Walks all 10 pilots (or the --tenant subset), pulls real Sentinel-1 VV
backscatter (60-day window) and Sentinel-2 NDVI (90-day window) time
series from the CDSE Statistical API, and upserts one row per
(tenant, observed_at, dataset, source) into satellite_observations.

PU cost (free-tier budget is 30000 PU/month):
  10 pilots × 2 datasets × 60-day windows ≈ 120 PU per full run.
  Safe to run daily; alert if it climbs over 500 PU/day (likely a
  rerun loop or oversized window).

NEVER point this at a production DB without:
  - Migration 0021 applied
  - COPERNICUS_CLIENT_ID + COPERNICUS_CLIENT_SECRET in the env
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from db import get_engine, get_session_factory  # noqa: E402
from tasks.satellite_observations_ingest import ingest_all  # noqa: E402


async def main(tenants: list[str] | None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    factory = get_session_factory()
    results = await ingest_all(factory, tenants=tenants)
    s1_total = sum(r.s1_points for r in results)
    s2_total = sum(r.s2_points for r in results)
    print(
        f"satellite.ingest complete — tenants={len(results)} "
        f"s1_rows={s1_total} s2_rows={s2_total}"
    )
    for r in results:
        print(
            f"  {r.tenant_id:9s}  S1 rows={r.s1_points:>3}  S2 rows={r.s2_points:>3}"
        )
    await get_engine().dispose()


def _parse_tenants(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant", help="single tenant id (shorthand for --tenants)",
    )
    parser.add_argument(
        "--tenants", help="comma-separated tenant ids; default = all pilots",
    )
    args = parser.parse_args()
    tenants = _parse_tenants(args.tenants or args.tenant)
    asyncio.run(main(tenants))
