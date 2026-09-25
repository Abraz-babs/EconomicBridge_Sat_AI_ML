"""Refresh Aid Coordination from IATI (d-portal) — also runs monthly on the scheduler.

    python -m scripts.run_aid_iati                       # every pilot tenant
    python -m scripts.run_aid_iati --tenant kebbi,fct
    python -m scripts.run_aid_iati --no-write            # plan and print, store nothing

Keyless; one d-portal fetch per country (~1 minute for Nigeria).
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from tasks.aid_iati_ingest import run_aid_iati_ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="comma-separated; default = every pilot tenant")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    tenants = [t.strip() for t in a.tenant.split(",")] if a.tenant else None
    out = asyncio.run(run_aid_iati_ingest(tenants, write=not a.no_write))
    for t, summary in out.items():
        print(f"AID_IATI {t}: {summary}")
    return 1 if any(s.startswith("FAILED") for s in out.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
