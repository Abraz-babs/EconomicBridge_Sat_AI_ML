"""Measure travel time to care at every village (Mobility Compass) — manual, rare.

    python -m scripts.run_village_access                    # every Nigerian pilot
    python -m scripts.run_village_access --tenant zamfara
    python -m scripts.run_village_access --no-write         # sample, store nothing

Re-run when the village layer gains villages or the Data for Children
Collaborative republishes its travel-time surfaces. Give the task 4 GB.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from tasks.village_access import run_village_access

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
for noisy in ("httpx", "httpcore", "rasterio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

NIGERIAN_PILOTS = ["kebbi", "zamfara", "niger", "kaduna", "benue", "plateau", "nasarawa", "fct"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = every Nigerian pilot")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    tenants = [t.strip() for t in a.tenant.split(",")] if a.tenant else NIGERIAN_PILOTS
    out = asyncio.run(run_village_access(tenants, write=not a.no_write))
    for t, summary in out.items():
        print(f"VILLAGE_ACCESS {t}: {summary}")
    return 0 if out and not any(s.error for s in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
