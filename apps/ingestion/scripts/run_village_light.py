"""Run the village-light scan (Economic Visibility) — seasonal, manual.

    python -m scripts.run_village_light --tenant kebbi,fct
    python -m scripts.run_village_light --tenant kebbi --no-write      # measure, store nothing

One round per year: clear dry-season nights (default: 12 nights to 20 March)
plus a wet-season check (default: 12 nights to 14 September) of the SAME year.
Measured 2026-09-24: ~4 minutes per state on 1 vCPU; give the task 8 GB.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

from tasks.village_light_scan import GRID3_STATE, run_village_light_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = every Nigerian pilot")
    ap.add_argument("--year", type=int, default=date.today().year, help="measurement round (default this year)")
    ap.add_argument("--dry-end", help="YYYY-MM-DD, last dry-season night (default <year>-03-20)")
    ap.add_argument("--wet-end", help="YYYY-MM-DD, last wet-season night (default <year>-09-14)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    tenants = [t.strip() for t in a.tenant.split(",")] if a.tenant else list(GRID3_STATE)
    dry_end = date.fromisoformat(a.dry_end) if a.dry_end else date(a.year, 3, 20)
    wet_end = date.fromisoformat(a.wet_end) if a.wet_end else date(a.year, 9, 14)
    out = asyncio.run(run_village_light_scan(tenants, dry_end=dry_end, wet_end=wet_end,
                                             period=str(a.year), write=not a.no_write))
    for t, summary in out.items():
        print(f"VILLAGE_LIGHT {t}: {summary}")
    return 1 if any(s.startswith("FAILED") for s in out.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
