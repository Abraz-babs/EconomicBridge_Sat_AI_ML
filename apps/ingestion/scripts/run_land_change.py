"""Run the whole-LGA land-change scan.

Seasonal, not scheduled: during evaluation this is launched by hand as a
one-shot Fargate task, so a multi-hour job can never disturb the live feeds
sharing the ingestion service.

    python -m scripts.run_land_change --tenant kebbi --max-lgas 3
    python -m scripts.run_land_change                       # all active tenants
    python -m scripts.run_land_change --no-write            # rehearse, write nothing

COST + RUNTIME (measured 2026-09-15, 1 vCPU, sequential reads)
    ~79 min for 3 LGAs (11.3M pixels). All 8 Nigerian pilots are ~309M pixels,
    so budget hours, not minutes, and roughly US$2 of Fargate per full run.
    This runner reads dates concurrently, which should cut that materially.

GIVE THE TASK 8 GB, NOT 4
    Each season holds its own accumulators, and the scan now reads THREE. At
    4 GB the kernel killed the zamfara/plateau/fct run outright (the log just
    says "Killed"), and Niger before it, both on their largest LGAs. 8 GB with
    1 vCPU completed Niger's 25 LGAs.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

from tasks.land_change_scan import run_land_change_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def _split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = active tenants")
    ap.add_argument("--lga", help="comma-separated LGA names")
    ap.add_argument("--max-lgas", type=int, help="first N LGAs per tenant")
    ap.add_argument("--end", help="YYYY-MM-DD; season window end (default today)")
    ap.add_argument("--no-write", action="store_true", help="scan but store nothing")
    args = ap.parse_args()

    out = await run_land_change_scan(
        _split(args.tenant),
        lgas=_split(args.lga),
        end=date.fromisoformat(args.end) if args.end else None,
        max_lgas=args.max_lgas,
        write=not args.no_write,
        trigger="manual",
    )
    for tenant, detail in sorted(out.items()):
        print("%-10s %s" % (tenant, detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
