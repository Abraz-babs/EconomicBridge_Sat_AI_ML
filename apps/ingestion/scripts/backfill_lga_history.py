"""One-time backfill: monthly per-LGA satellite history for seasonal baselines.

Usage (from apps/ingestion/ with the venv active):
    python -m scripts.backfill_lga_history                 # all pilots
    python -m scripts.backfill_lga_history --tenant kebbi  # one tenant
    python -m scripts.backfill_lga_history --start 2023-01 # custom start

Walks every LGA centroid (same ~3 km boxes + resolution the live encroachment
sweep uses, so the history is geometrically consistent with the live series)
and pulls MONTHLY (P1M) aggregates from the CDSE Statistical API:

  * Sentinel-2 NDVI (per-pixel cloud-masked)  -> signal 'ndvi'
  * Sentinel-1 VV backscatter (dB)            -> signal 'sar_vv_db'

Rows land in public.lga_signal_history via idempotent upsert — safe to re-run
or resume after an interruption; nothing else reads the table yet (Tier-A
prep for the Sep–Oct seasonal-baseline sprint; live behavior unchanged).

PU budget: ~447 LGAs × 2 signals = ~894 Statistical requests, one-time.
Monthly aggregation over a 3 km box is light per request; the client's
Retry-After-aware 429 backoff handles the free-tier per-minute limit. A full
run takes roughly 30–60 minutes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from sqlalchemy import text  # noqa: E402

from db import PILOT_TENANT_IDS, get_engine, get_session_factory  # noqa: E402
from sources.copernicus import CopernicusClient, CopernicusError  # noqa: E402
from sources.farm_check import FARM_RESOLUTION_DEG, bbox_around  # noqa: E402
from sources.sentinel_statistical import (  # noqa: E402
    EVALSCRIPT_S1_VV_DB,
    EVALSCRIPT_S2_NDVI_CLOUDMASKED,
    SentinelStatisticalClient,
    StatPoint,
)
from tasks.encroachment_detector import LGA_BOX_HALF_M  # noqa: E402

log = logging.getLogger("backfill_lga_history")

_CENTROIDS_PATH = INGESTION_ROOT / "data" / "lga_centroids.json"

_SIGNALS: list[tuple[str, str, str]] = [
    # (signal key, dataset, evalscript)
    ("ndvi", "sentinel-2-l2a", EVALSCRIPT_S2_NDVI_CLOUDMASKED),
    ("sar_vv_db", "sentinel-1-grd", EVALSCRIPT_S1_VV_DB),
]

_UPSERT = text("""
    INSERT INTO public.lga_signal_history (
        tenant_id, lga, lon, lat, signal, period_start,
        mean, std_dev, sample_count
    ) VALUES (
        :tenant, :lga, :lon, :lat, :signal, :period_start,
        :mean, :std_dev, :sample_count
    )
    ON CONFLICT ON CONSTRAINT uq_lga_hist DO UPDATE SET
        mean = EXCLUDED.mean,
        std_dev = EXCLUDED.std_dev,
        sample_count = EXCLUDED.sample_count,
        fetched_at = NOW()
""")


def _load_centroids(tenants: list[str]) -> dict[str, list[dict]]:
    raw = json.loads(_CENTROIDS_PATH.read_text(encoding="utf-8"))
    return {t: raw.get(t, []) for t in tenants if raw.get(t)}


async def _store(session, *, tenant: str, g: dict, signal: str,
                 points: list[StatPoint]) -> int:
    n = 0
    for p in points:
        if p.mean is None:
            continue  # fully-masked interval — no honest number to store
        await session.execute(_UPSERT, {
            "tenant": tenant, "lga": g["lga"], "lon": g["lon"], "lat": g["lat"],
            "signal": signal, "period_start": p.interval_from.date(),
            "mean": p.mean, "std_dev": p.std_dev,
            "sample_count": p.sample_count,
        })
        n += 1
    return n


async def main(tenants: list[str] | None, start: datetime) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    target = tenants or sorted(PILOT_TENANT_IDS)
    centroids = _load_centroids(target)
    total_lgas = sum(len(v) for v in centroids.values())
    end = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    log.info("backfill: %d tenants, %d LGAs, window %s -> %s (monthly)",
             len(centroids), total_lgas, start.date(), end.date())

    client = SentinelStatisticalClient(CopernicusClient())
    if not client.configured:
        log.error("COPERNICUS credentials not configured — aborting")
        return

    factory = get_session_factory()
    done = rows = failures = 0
    async with factory() as session:
        for tenant, lgas in centroids.items():
            for g in lgas:
                bbox = bbox_around(g["lat"], g["lon"], LGA_BOX_HALF_M)
                for signal, dataset, evalscript in _SIGNALS:
                    try:
                        points = await client.compute_time_series(
                            bbox=bbox, start=start, end=end,
                            dataset=dataset, evalscript=evalscript,
                            agg_interval="P1M",
                            resolution_deg=FARM_RESOLUTION_DEG,
                        )
                        rows += await _store(
                            session, tenant=tenant, g=g,
                            signal=signal, points=points)
                    except CopernicusError as exc:
                        failures += 1
                        log.warning("%s/%s %s failed: %s",
                                    tenant, g["lga"], signal, exc)
                await session.commit()   # per-LGA commit → resumable
                done += 1
                if done % 25 == 0:
                    log.info("progress: %d/%d LGAs, %d rows, %d failures",
                             done, total_lgas, rows, failures)
    log.info("backfill COMPLETE: %d/%d LGAs, %d rows upserted, %d failures",
             done, total_lgas, rows, failures)
    await get_engine().dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", "--tenants", dest="tenants", default=None,
                    help="comma-separated tenant ids (default: all pilots)")
    ap.add_argument("--start", default="2023-01",
                    help="history start as YYYY-MM (default 2023-01)")
    args = ap.parse_args()
    tenants = ([t.strip() for t in args.tenants.split(",") if t.strip()]
               if args.tenants else None)
    start = datetime.strptime(args.start, "%Y-%m").replace(tzinfo=timezone.utc)
    asyncio.run(main(tenants, start))
