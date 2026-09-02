"""Backfill the per-LGA storm intensity record so ratings can start now.

WHY
---
`tasks/storm_scan.py` rates a storm by where it sits in that LGA's own
intensity record, and refuses to rate anything until MIN_BASELINE_DAYS (21) of
record exist. That rule is right — "highest in 4 days" must not be presentable
as "highest in 90" — but it means a freshly-deployed engine says nothing for
three weeks.

This backfills that record from the archive so the engine is useful on day one.
It is a ONE-OFF (or a re-run after adding a tenant); the daily scan grows the
record by itself thereafter.

COST
----
48 slices per day per region. Three regions over N days is N x 144 requests to
GES DISC — for 28 days, about 4,000. That is bounded, one-off, and NASA (free,
off the CDSE Processing-Unit budget), but it is not fast: expect a couple of
hours. Run it detached.

Deliberately fetches ALL 48 slices per day rather than sampling every other
one. Halving the fetch would halve the cost and bias every accumulation low —
and a baseline biased against the live measurement is worse than no baseline,
because the comparison silently over-rates every future storm.

    python -m scripts.bootstrap_storm_baseline [--days 28] [--region nigeria]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.storm_event import find_storms
from sources.gpm_imerg_halfhourly import ImergHalfHourlyClient
from tasks.encroachment_detector import select_lgas
from tasks.rainstorm_scan import TENANT_REGION
from tasks.storm_scan import _degrees

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# The Final run lags ~3.5 months, so the archive we can reach for recent days
# is the Late run — the same one the live scan uses. Consistency between the
# baseline and the measurement matters more here than absolute accuracy.
SLICES_PER_DAY = 48


async def backfill_day(
    client: ImergHalfHourlyClient, http: httpx.AsyncClient,
    region: str, day_end: datetime, tenants: list[str],
) -> tuple[int, int]:
    """One UTC day for one region. Returns (slices, lga rows written)."""
    lon_min, lon_max, lat_min, lat_max = _degrees(region)
    grids = await client.window(
        lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max,
        end=day_end, hours=24,
    )
    if not grids:
        return 0, 0

    day = (day_end - timedelta(hours=12)).date()
    written = 0
    factory = get_session_factory()
    for tenant in tenants:
        async with factory() as session:
            await set_tenant_schema(session, tenant)
            for g in select_lgas(tenant, full=True):
                series = []
                for grid in grids:
                    v = grid.sample_max(g["lon"], g["lat"])
                    if v is not None:
                        series.append((grid.at, v))
                events = find_storms(series)
                if not events:
                    continue
                e = max(events, key=lambda x: x.total_mm)
                await session.execute(text("""
                    INSERT INTO storm_intensity_daily (
                        tenant_id, lga, day, max_1h_mm, max_3h_mm, max_6h_mm,
                        peak_mm_hr, slices_seen, slices_expected
                    ) VALUES (:t, :lga, :day, :h1, :h3, :h6, :peak, :seen, :exp)
                    ON CONFLICT (lga, day) DO UPDATE SET
                        max_1h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_1h_mm, 0), EXCLUDED.max_1h_mm),
                        max_3h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_3h_mm, 0), EXCLUDED.max_3h_mm),
                        max_6h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_6h_mm, 0), EXCLUDED.max_6h_mm),
                        peak_mm_hr = GREATEST(COALESCE(storm_intensity_daily.peak_mm_hr, 0), EXCLUDED.peak_mm_hr),
                        slices_seen = GREATEST(storm_intensity_daily.slices_seen, EXCLUDED.slices_seen)
                """), {
                    "t": tenant, "lga": g["lga"], "day": day,
                    "h1": e.accum.get(1, 0.0), "h3": e.accum.get(3, 0.0),
                    "h6": e.accum.get(6, 0.0), "peak": e.peak_mm_hr,
                    "seen": len(grids), "exp": SLICES_PER_DAY,
                })
                written += 1
            await session.commit()
    return len(grids), written


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--region", default=None,
                    help="limit to one region (nigeria|ghana|senegal)")
    args = ap.parse_args()

    client = ImergHalfHourlyClient()
    if not client.configured:
        raise SystemExit("EARTHDATA_TOKEN not set")

    by_region: dict[str, list[str]] = {}
    for t in sorted(PILOT_TENANT_IDS):
        r = TENANT_REGION.get(t)
        if r and (args.region is None or r == args.region):
            by_region.setdefault(r, []).append(t)

    # Yesterday backwards; today is still being published.
    base = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)

    total_slices = total_rows = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0),
                                 follow_redirects=True) as http:
        for region, tenants in sorted(by_region.items()):
            for d in range(1, args.days + 1):
                day_end = base - timedelta(days=d - 1)
                try:
                    s, w = await backfill_day(client, http, region, day_end, tenants)
                except Exception:  # noqa: BLE001 — one day must not stop the run
                    log.exception("backfill failed region=%s day=%s", region, day_end)
                    continue
                total_slices += s
                total_rows += w
                log.info(
                    "%s %s: %d slices, %d LGA rows (running %d/%d)",
                    region, (day_end - timedelta(hours=12)).date(), s, w,
                    total_rows, total_slices,
                )
    log.info("bootstrap complete: %d slices, %d LGA-day rows",
             total_slices, total_rows)


if __name__ == "__main__":
    asyncio.run(main())
