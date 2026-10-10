"""Run the pre-season risk profile — yearly, manual, before planting.

    python -m scripts.run_risk_profile                          # every pilot, through last season
    python -m scripts.run_risk_profile --tenant kebbi --through 2025
    python -m scripts.run_risk_profile --no-write --dump /tmp/rp.json   # measure, store nothing

CHIRPS publishes a month's rainfall about three weeks after it ends, so a
season is complete once its October is out; --through defaults to the latest
season whose October monthly file exists. Reading 1998 onward of daily
rainfall for all ten pilots moves about 9 GB; give the task 2 vCPU and 8 GB.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import warnings
from datetime import date

import httpx

from tasks.risk_profile import CHIRPS_MONTHLY, run_risk_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
# A cut-short read is retried by the task; GDAL's per-tag warnings about it are noise.
logging.getLogger("rasterio").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*no geotransform.*")

PILOTS = ["kebbi", "zamfara", "niger", "kaduna", "benue", "plateau", "nasarawa", "fct", "ghana", "senegal"]


def last_complete_season() -> int:
    for y in range(date.today().year, date.today().year - 3, -1):
        r = httpx.head(CHIRPS_MONTHLY.format(y=y, m=10), timeout=30, follow_redirects=True)
        if r.status_code == 200:
            return y
    raise SystemExit("no CHIRPS October file found in the last three years")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = every pilot")
    ap.add_argument("--through", type=int, help="last season (default: latest complete)")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--no-daily", action="store_true", help="skip the daily dry-spell read (quick runs)")
    ap.add_argument("--dump", help="write the rows (and overlays as base64) to this JSON file")
    a = ap.parse_args()
    tenants = [t.strip() for t in a.tenant.split(",")] if a.tenant else PILOTS
    through = a.through or last_complete_season()
    collect: dict | None = {} if a.dump else None
    out = asyncio.run(run_risk_profile(tenants, through=through, write=not a.no_write,
                                       daily=not a.no_daily, collect=collect))
    for t, summary in out.items():
        print(f"RISK_PROFILE {t} through {through}: {summary}")
    if a.dump and collect is not None:
        doc = {t: {"rows": [{**r, "figures": json.loads(r["figures"])} for r in v["rows"]],
                   "overlays": [{**o, "png": base64.b64encode(o["png"]).decode()} for o in v["overlays"]]}
               for t, v in collect.items()}
        with open(a.dump, "w", encoding="utf-8") as fh:
            json.dump({"through": through, "tenants": doc}, fh)
        print(f"dumped to {a.dump}")
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
