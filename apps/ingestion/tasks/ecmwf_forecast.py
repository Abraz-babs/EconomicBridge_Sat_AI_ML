"""Daily ECMWF forecast — the next 15 days for every LGA of every pilot.

WHAT IT IS
----------
Reads ECMWF's open forecast (CC BY 4.0) once a day and stores, per LGA, what
it says about the coming days: rain from the physics model (IFS) and the AI
model (AIFS) side by side, the ensemble's chance of a wet, soaking, heavy and
very heavy day, and dawn and afternoon temperature. The observed side of
ShockGuard (IMERG rainfall, storms, radar) is untouched; this adds the
forecast beside it.

WHAT IT CLAIMS, AND WHAT IT DOES NOT
------------------------------------
A forecast, not a measurement. The free feed is 0.25 deg (about 28 km), so it
gives LGA-level outlooks, never village-level ones, and every value is an
area average with the wettest cell kept beside it. Days 11-15 come from a
single run and have lower skill; ensemble chances stop at day 10. Nothing here
issues an alert or an SMS.

ONLY THE 00 UTC RUN
-------------------
Its days line up with UTC calendar days (00-24 UTC is 01:00-01:00 in Nigeria),
so "Tuesday" means one thing in every row. It is fully published by 08:01 UTC;
the job runs at 09:15 and again at 13:15 in case the first try was early.
Every run is kept — rows are append-only, one per LGA per run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.forecast_lga import (
    ForecastFields,
    Weights,
    area_weights,
    daily_totals,
    summarise,
    window_for,
)
from sources import lga_boundaries
from sources.ecmwf_opendata import (
    AIFS,
    BASE_URL,
    ENS_CHANCES,
    IFS,
    Domain,
    EcmwfOpenDataClient,
    Run,
)

log = logging.getLogger(__name__)

# public.ingestion_runs key. Also listed in the API's feed-health budgets
# (services/feed_health.py FEED_MAX_AGE_HOURS) so a silent feed is noticed.
SOURCE = "ecmwf_forecast_v1"

DAYS = 15
CHANCE_DAYS = 10
TEMP_DAYS = 6
CHANCE_THRESHOLDS = (1, 10, 25, 50)
DAWN_STEP, AFTERNOON_STEP = 6, 15      # hours after 00 UTC: 07:00 and 16:00 in Nigeria
KELVIN = 273.15
DOMAIN_MARGIN_DEG = 0.5

_weights: dict[tuple[str, str], Weights] = {}


def pilot_domain() -> Domain:
    """The grid window covering every pilot LGA, with a margin."""
    boxes = [b.bbox for t in PILOT_TENANT_IDS for b in lga_boundaries.for_tenant(t)]
    m = DOMAIN_MARGIN_DEG
    return Domain.around(min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m,
                         max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)


def tenant_bbox(tenant: str) -> tuple[float, float, float, float]:
    """A tenant's outer box from its LGA outlines."""
    boxes = [b.bbox for b in lga_boundaries.for_tenant(tenant)]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def weights_for(tenant: str, lga: str, geometry: dict, domain: Domain) -> Weights:
    """Area weights, computed once per LGA per process (outlines do not change)."""
    key = (tenant, lga)
    if key not in _weights:
        _weights[key] = area_weights(geometry, domain)
    return _weights[key]


async def _one(client: EcmwfOpenDataClient, run: Run, product: tuple[str, str, str],
               step: int, param: str, domain: Domain, base: str = BASE_URL) -> np.ndarray:
    fields = await client.fields(run.url(product, step, base),
                                 lambda e: e.get("param") == param and e.get("levtype") == "sfc",
                                 keep=domain.crop)
    if len(fields) != 1:
        raise RuntimeError(f"{param} at {step} h: expected 1 field, found {len(fields)}")
    return fields[0][1]


async def _chances(client: EcmwfOpenDataClient, run: Run, domain: Domain,
                   base: str = BASE_URL) -> dict[int, list[np.ndarray]]:
    """The ensemble's daily chances for each threshold, days 0..9, all or nothing."""
    windows = {f"{24 * d}-{24 * (d + 1)}": d for d in range(CHANCE_DAYS)}
    wanted = {f"tpg{t}": t for t in CHANCE_THRESHOLDS}
    got = await client.fields(
        run.url(ENS_CHANCES, 24 * CHANCE_DAYS, base),
        lambda e: e.get("type") == "ep" and e.get("param") in wanted and e.get("step") in windows,
        keep=domain.crop)
    grids: dict[int, list[np.ndarray | None]] = {t: [None] * CHANCE_DAYS for t in CHANCE_THRESHOLDS}
    for entry, grid in got:
        grids[wanted[entry["param"]]][windows[entry["step"]]] = grid
    out: dict[int, list[np.ndarray]] = {}
    for t, days in grids.items():
        complete = [g for g in days if g is not None]
        if len(complete) != CHANCE_DAYS:
            raise RuntimeError(f"ensemble chance of {t} mm+: {len(complete)} of {CHANCE_DAYS} days")
        out[t] = complete
    return out


async def fetch_fields(client: EcmwfOpenDataClient, run: Run, have: set[str],
                       domain: Domain) -> tuple[ForecastFields, list[str]]:
    """Read and crop everything one run contributes.

    The physics model is required. The AI model and the ensemble chances are
    not: if either is missing or fails to read, it stays None (shown as "not
    available" to the reader, never borrowed from another product) and the
    problem is returned so the run record says so.
    """
    steps = [24 * (d + 1) for d in range(DAYS)]
    ifs = [await _one(client, run, IFS, s, "tp", domain) for s in steps]
    dawn = [await _one(client, run, IFS, DAWN_STEP + 24 * d, "2t", domain) - KELVIN
            for d in range(TEMP_DAYS)]
    afternoon = [await _one(client, run, IFS, AFTERNOON_STEP + 24 * d, "2t", domain) - KELVIN
                 for d in range(TEMP_DAYS)]
    problems: list[str] = [f"{name} not published" for name in ("aifs", "ens") if name not in have]
    aifs = None
    if "aifs" in have:
        try:
            aifs = daily_totals([await _one(client, run, AIFS, s, "tp", domain) for s in steps])
        except Exception as exc:  # noqa: BLE001 — degrade to "not available", and say so
            log.exception("ecmwf forecast: AIFS read failed")
            problems.append(f"aifs failed: {exc!r}")
    chances = None
    if "ens" in have:
        try:
            chances = await _chances(client, run, domain)
        except Exception as exc:  # noqa: BLE001 — degrade to "not available", and say so
            log.exception("ecmwf forecast: ensemble chances read failed")
            problems.append(f"ens failed: {exc!r}")
    fields = ForecastFields(rain_ifs=daily_totals(ifs, scale=1000.0), rain_aifs=aifs,
                            chances=chances, temp_dawn=dawn, temp_afternoon=afternoon)
    return fields, problems


def _js(v: object) -> str | None:
    return None if v is None else json.dumps(v)


async def _store_tenant(session: AsyncSession, tenant: str, run: Run,
                        fields: ForecastFields, domain: Domain, *,
                        source: str = SOURCE, with_cells: bool = True) -> int:
    """Write one run for one tenant: a row per LGA plus the raw cells. Returns rows written.

    The forecast-check backfill reuses this for runs read later from ECMWF's
    archive: it passes its own `source`, so those rows are never mistaken for
    the live feed's, and skips the cell layer, which only the newest run feeds.
    """
    rows = []
    for b in lga_boundaries.for_tenant(tenant):
        fc = summarise(b.lga, weights_for(tenant, b.lga, b.geometry, domain), fields)
        ch = fc.chance or {}
        rows.append({
            "t": tenant, "lga": fc.lga, "run": run.base_time, "first": run.day, "cells": fc.cells,
            "ifs": _js(fc.rain_ifs_mm), "ifs_max": _js(fc.rain_ifs_max_mm), "aifs": _js(fc.rain_aifs_mm),
            "c1": _js(ch.get(1)), "c10": _js(ch.get(10)), "c25": _js(ch.get(25)), "c50": _js(ch.get(50)),
            "dawn": _js(fc.temp_dawn_c), "aft": _js(fc.temp_afternoon_c), "src": source,
        })
    await session.execute(text("""
        INSERT INTO ecmwf_forecast (
            tenant_id, lga, run_at, first_day, cells, rain_ifs_mm, rain_ifs_max_mm, rain_aifs_mm,
            chance_1mm, chance_10mm, chance_25mm, chance_50mm, temp_dawn_c, temp_afternoon_c, source
        ) VALUES (
            :t, :lga, :run, :first, :cells, CAST(:ifs AS JSONB), CAST(:ifs_max AS JSONB),
            CAST(:aifs AS JSONB), CAST(:c1 AS JSONB), CAST(:c10 AS JSONB), CAST(:c25 AS JSONB),
            CAST(:c50 AS JSONB), CAST(:dawn AS JSONB), CAST(:aft AS JSONB), :src
        )
        ON CONFLICT (lga, run_at) DO NOTHING
    """), rows)
    if not with_cells:
        return len(rows)

    win = window_for(domain, tenant_bbox(tenant))
    await session.execute(text("""
        INSERT INTO ecmwf_forecast_cells (
            tenant_id, run_at, lat0, lon0, res, n_rows, n_cols,
            rain_ifs_mm, rain_aifs_mm, chance_10mm, source
        ) VALUES (
            :t, :run, :lat0, :lon0, 0.25, :nr, :nc,
            CAST(:ifs AS JSONB), CAST(:aifs AS JSONB), CAST(:c10 AS JSONB), :src
        )
        ON CONFLICT (run_at) DO NOTHING
    """), {
        "t": tenant, "run": run.base_time, "lat0": win.lat0, "lon0": win.lon0,
        "nr": win.n_rows, "nc": win.n_cols, "src": SOURCE,
        "ifs": _js([win.take(g) for g in fields.rain_ifs]),
        "aifs": _js(None if fields.rain_aifs is None else [win.take(g) for g in fields.rain_aifs]),
        "c10": _js(None if fields.chances is None else [win.take(g, 0) for g in fields.chances[10]]),
    })
    return len(rows)


async def _stored(session: AsyncSession, run: Run) -> bool:
    return (await session.execute(
        text("SELECT 1 FROM ecmwf_forecast WHERE run_at = :r LIMIT 1"), {"r": run.base_time},
    )).first() is not None


async def _record_run(session: AsyncSession, *, tenant: str, written: int, started_at: datetime,
                      trigger: str, error: str | None = None, note: str | None = None) -> None:
    """Stamp public.ingestion_runs on EVERY outcome, so a dead feed never reads as quiet."""
    await session.execute(text("""
        INSERT INTO public.ingestion_runs (
            id, source, tenant_id, trigger, started_at, finished_at,
            status, records_ingested, error_message, dry_run
        ) VALUES (:id, :source, :tenant, :trigger, :started_at, NOW(), :status, :written, :error, FALSE)
    """), {
        "id": uuid4(), "source": SOURCE, "tenant": tenant, "trigger": trigger,
        "started_at": started_at, "written": written,
        "status": "failed" if error else "succeeded",
        "error": (error or note or "")[:500] or None,
    })


async def run_ecmwf_forecast(tenants: list[str] | None = None, *,
                             trigger: str = "scheduled") -> dict[str, str]:
    """Store the newest complete 00 UTC run for every pilot. Failures isolated per tenant."""
    started_at = datetime.now(timezone.utc)
    target = sorted(tenants if tenants is not None else PILOT_TENANT_IDS)
    domain = pilot_domain()
    out: dict[str, str] = {}
    factory = get_session_factory()
    fields: ForecastFields | None = None
    error: str | None = None
    note: str | None = None
    run: Run | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as http:
            client = EcmwfOpenDataClient(http)
            found = await client.latest_run(started_at)
            if found is None:
                error = "no complete 00 UTC run published in the last 2 days"
            else:
                run, have = found
                fields, problems = await fetch_fields(client, run, have, domain)
                # Only a real gap is written to the run record; a clean run carries none.
                note = f"partial run {run.base_time:%Y-%m-%d} 00 UTC: {'; '.join(problems)}" if problems else None
    except Exception as exc:  # noqa: BLE001 — recorded per tenant below, never swallowed
        log.exception("ecmwf forecast: fetch failed")
        error = f"fetch failed: {exc!r}"

    for tenant in target:
        try:
            async with factory() as session:
                await set_tenant_schema(session, tenant)
                if error or fields is None or run is None:
                    await _record_run(session, tenant=tenant, written=0, started_at=started_at,
                                      trigger=trigger, error=error or "no data")
                    out[tenant] = f"failed: {error}"
                elif await _stored(session, run):
                    await _record_run(session, tenant=tenant, written=0, started_at=started_at,
                                      trigger=trigger)
                    out[tenant] = f"run {run.base_time:%Y-%m-%d} 00 UTC already stored"
                else:
                    n = await _store_tenant(session, tenant, run, fields, domain)
                    await _record_run(session, tenant=tenant, written=n, started_at=started_at,
                                      trigger=trigger, note=note)
                    out[tenant] = f"{n} LGAs · run {run.base_time:%Y-%m-%d} 00 UTC" + (f" · {note}" if note else "")
                await session.commit()
        except Exception as exc:  # noqa: BLE001 — isolate per tenant, and record it
            log.exception("ecmwf forecast failed tenant=%s", tenant)
            out[tenant] = f"failed: {exc!r}"
            try:
                async with factory() as session:
                    await _record_run(session, tenant=tenant, written=0, started_at=started_at,
                                      trigger=trigger, error=repr(exc))
                    await session.commit()
            except Exception:  # noqa: BLE001 — never mask the real failure
                log.exception("ecmwf forecast: could not record failed run tenant=%s", tenant)
    log.info("ecmwf forecast: %s", out)
    return out
