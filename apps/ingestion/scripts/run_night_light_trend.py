"""Run the night-light trend (Mobility Compass) — yearly, manual.

    python -m scripts.run_night_light_trend                          # Nigerian pilots, 2012 → last year
    python -m scripts.run_night_light_trend --tenant kebbi --to 2025
    python -m scripts.run_night_light_trend --no-write               # measure, store nothing

NASA publishes a year's composite (VNP46A4) in the following year; re-run
once it lands to add that year. Earlier years are re-read and rewritten only
where NASA changed them. Measured 2026-09-27: three tiles × 14 years for the
8 Nigerian pilots in about 30 minutes; give the task 6 GB.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

from tasks.night_light_trend import run_night_light_trend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

NIGERIAN_PILOTS = ["kebbi", "zamfara", "niger", "kaduna", "benue", "plateau", "nasarawa", "fct"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = every Nigerian pilot")
    ap.add_argument("--from", dest="first", type=int, default=2012, help="first year (default 2012)")
    ap.add_argument("--to", dest="last", type=int, default=date.today().year - 1,
                    help="last year (default last year)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    tenants = [t.strip() for t in a.tenant.split(",")] if a.tenant else NIGERIAN_PILOTS
    out = asyncio.run(run_night_light_trend(tenants, first_year=a.first, last_year=a.last,
                                            write=not a.no_write))
    for t, summary in out.items():
        print(f"NIGHT_LIGHT {t}: {summary}")
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
