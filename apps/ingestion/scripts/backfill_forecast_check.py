"""Start the forecast check with the 2026 rainy season instead of an empty page.

WHY
---
The live forecast feed began storing runs on 2026-11-17, in the dry season.
Checked from that day alone, the page would say almost nothing until the rains
return in 2027, and "the forecast called a dry day dry" is the easy half of the
test. ECMWF keeps its open-data runs on cloud mirrors well beyond the ~4 days
data.ecmwf.int holds, so the season can be checked now.

WHAT IT WRITES
--------------
1. ECMWF 00 UTC runs from the archive (sources/ecmwf_opendata.ARCHIVE_URL,
   the same files data.ecmwf.int served on the day) into ecmwf_forecast with
   source 'ecmwf_archive_v1', so a run read later is never mistaken for one
   the live feed captured. Rain from both models and the ensemble chances only:
   temperature is not checked, so it is not fetched (NULL), and the map's cell
   layer is not written (only the newest run feeds it). The same weighting and
   rounding as the live feed (tasks/ecmwf_forecast._store_tenant).
   Refuses any run on or after the first one the live feed stored, so it can
   never sit in front of the live forecast.
2. IMERG Late per LGA for the same days (tasks/forecast_check.measure_days).
3. One scorecard per tenant.

Resumable: a run or a day already held is skipped. Append-only.

COST
----
Per run about 100 requests and 30 MB from the mirror (15 + 15 rain fields and
40 ensemble chances); 200 runs is ~6 GB, run four at a time. IMERG is three
requests per day. Expect well under an hour as a one-shot ECS task.

    python -m scripts.backfill_forecast_check --start 2026-05-01 [--end 2026-11-16]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.forecast_lga import ForecastFields, daily_totals
from sources.ecmwf_opendata import AIFS, ARCHIVE_URL, IFS, Domain, EcmwfOpenDataClient, Run
from sources.gpm_imerg import GpmImergClient
from tasks import ecmwf_forecast as ef
from tasks import forecast_check as fc

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

ARCHIVE_SOURCE = "ecmwf_archive_v1"
# Each field in flight briefly holds its global grid (~8 MB as float64, plus
# eccodes' own copy) until it is cropped; eight at a time stays well inside the
# task's memory. The first attempt, with every ensemble field held whole and four
# runs in flight, was killed for memory inside a minute (2026-11-17).
RUNS_IN_FLIGHT = 3
FIELDS_IN_FLIGHT = 8


async def _live_first_day(tenants: list[str]) -> date | None:
    """The first run the live feed stored, across tenants (None before any)."""
    factory = get_session_factory()
    firsts = []
    for t in tenants:
        async with factory() as s:
            await set_tenant_schema(s, t)
            firsts.append((await s.execute(text(
                "SELECT MIN(first_day) FROM ecmwf_forecast WHERE source = :s"), {"s": ef.SOURCE})).scalar())
    known = [d for d in firsts if d is not None]
    return min(known) if known else None


async def _missing(run: Run, tenants: list[str]) -> list[str]:
    factory = get_session_factory()
    out = []
    for t in tenants:
        async with factory() as s:
            await set_tenant_schema(s, t)
            if (await s.execute(text("SELECT 1 FROM ecmwf_forecast WHERE run_at = :r LIMIT 1"),
                                {"r": run.base_time})).first() is None:
                out.append(t)
    return out


async def _fetch(client: EcmwfOpenDataClient, run: Run, domain: Domain,
                 gate: asyncio.Semaphore) -> tuple[ForecastFields, list[str]]:
    """Rain from both models and the ensemble chances, read from the archive."""
    steps = [24 * (d + 1) for d in range(ef.DAYS)]

    async def tp(product: tuple[str, str, str], step: int):  # noqa: ANN202
        async with gate:
            return await ef._one(client, run, product, step, "tp", domain, ARCHIVE_URL)

    ifs = await asyncio.gather(*(tp(IFS, s) for s in steps))
    problems: list[str] = []
    aifs = None
    try:
        aifs = daily_totals(list(await asyncio.gather(*(tp(AIFS, s) for s in steps))))
    except Exception as exc:  # noqa: BLE001 — missing stays missing, and is reported
        problems.append(f"aifs: {exc!r}")
    chances = None
    try:
        async with gate:
            chances = await ef._chances(client, run, domain, ARCHIVE_URL)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"ens: {exc!r}")
    return ForecastFields(rain_ifs=daily_totals(list(ifs), scale=1000.0), rain_aifs=aifs, chances=chances,
                          temp_dawn=None, temp_afternoon=None), problems


async def backfill_forecasts(days: list[date], tenants: list[str]) -> None:
    """Read and store every run in `days` that some tenant lacks."""
    domain = ef.pilot_domain()
    factory = get_session_factory()
    queue: asyncio.Queue[date] = asyncio.Queue()
    for d in days:
        queue.put_nowait(d)
    gate = asyncio.Semaphore(FIELDS_IN_FLIGHT)
    done, t0 = 0, time.monotonic()

    async def worker(client: EcmwfOpenDataClient) -> None:
        nonlocal done
        while not queue.empty():
            run = Run(queue.get_nowait(), 0)
            todo = await _missing(run, tenants)
            if todo:
                try:
                    fields, problems = await _fetch(client, run, domain, gate)
                except Exception as exc:  # noqa: BLE001 — one run lost, the rest go on
                    log.warning("archive run %s failed: %r", run.day, exc)
                    continue
                for t in todo:
                    async with factory() as s:
                        await set_tenant_schema(s, t)
                        await ef._store_tenant(s, t, run, fields, domain, source=ARCHIVE_SOURCE, with_cells=False)
                        await s.commit()
                if problems:
                    log.warning("archive run %s partial: %s", run.day, "; ".join(problems))
            done += 1
            if done % 10 == 0 or done == len(days):
                log.info("archive runs %d/%d (%.1f min)", done, len(days), (time.monotonic() - t0) / 60)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as http:
        client = EcmwfOpenDataClient(http)
        await asyncio.gather(*(worker(client) for _ in range(RUNS_IN_FLIGHT)))


def runs_to_fetch(start: date, end: date | None, live_first: date | None, today: date) -> list[date]:
    """Run days to read from the archive: from `start`, and strictly BEFORE the
    first run the live feed stored (or today, before it has stored any). An
    archive row must never sit in front of the live forecast or pre-empt it."""
    last = (live_first or today) - timedelta(days=1)
    if end is not None:
        last = min(last, end)
    return [start + timedelta(days=k) for k in range((last - start).days + 1)]


async def main(start: date, end: date | None) -> None:
    """Forecasts, then measurements, then one scorecard per tenant."""
    tenants = sorted(PILOT_TENANT_IDS)
    today = datetime.now(timezone.utc).date()
    live_first = await _live_first_day(tenants)
    runs = runs_to_fetch(start, end, live_first, today)
    log.info("backfill: %d archive runs from %s (live feed starts %s)", len(runs), start, live_first)
    await backfill_forecasts(runs, tenants)

    measured_days = [start + timedelta(days=k) for k in range((today - start).days)]
    client = GpmImergClient()
    try:
        added, notes = await fc.measure_days(client, measured_days, tenants)
    finally:
        client.close()
    log.info("backfill: measured rows added %s; notes %s", added, notes)

    factory = get_session_factory()
    for t in tenants:
        async with factory() as s:
            await set_tenant_schema(s, t)
            log.info("backfill: %s %s", t, await fc.summarise_tenant(s, t, today))
            await s.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))
