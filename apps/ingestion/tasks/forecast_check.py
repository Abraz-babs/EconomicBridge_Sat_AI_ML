"""Daily forecast check: the rain that fell in every LGA against what ECMWF forecast.

WHAT IT DOES
------------
1. Measures. For each recent UTC day not yet held, reads NASA's IMERG Late
   daily rain over each region (one request covers every LGA in it) and stores,
   per LGA, the area-weighted rain, the wettest cell and the share of the LGA
   that reached 1/10/25/50 mm (rain_measured_daily, append-only). The weighting
   matches the forecast's, so the two sides are like for like.
2. Scores. Recomputes the scorecard per tenant from everything held — the
   measured days against the stored ECMWF runs made 0-14 days before each —
   and appends it to forecast_check_summary when anything changed.

Nothing is sent to anyone: this is a record of how the forecast did, kept
beside the forecast. It never alters a forecast or an observation.

WHY THE IMERG LATE RUN
----------------------
Its daily file covers 00-24 UTC, the same day the 00 UTC forecast's days use,
and it is published about a day later (16 Nov was readable by 18:15 UTC on
17 Nov). The Final run is better but lags ~3.5 months; `product` is part of the
table key so it can be added beside Late later without replacing anything.

A satellite estimate, not a rain gauge: the check says how often two
independent estimates agree, never "accuracy" (processors/rain_check.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.rain_check import (
    LEADS,
    CellWeights,
    RegionArray,
    box_for,
    build_record,
    imerg_weights,
    measure,
    region_array,
    summarise_record,
)
from sources import lga_boundaries
from sources.gpm_imerg import GpmImergClient, ImergAuthError

log = logging.getLogger(__name__)

# public.ingestion_runs key; budgeted in the API's services/feed_health.py.
SOURCE = "forecast_check_v1"
MEASURED_SOURCE = "imerg_lga_daily_v1"
PRODUCT = "GPM_3IMERGDL.07"          # IMERG Late, daily, V07

LOOKBACK_DAYS = 10                   # re-asks for days whose file came late
HISTORY_DAYS = 365                   # the scorecard's window
MIN_COVERAGE = 0.9                   # an LGA-day with less valid area is not stored
MAX_BEHIND_DAYS = 4                  # newest measured day older than this = a failed feed
MAX_CONSECUTIVE_FAILURES = 10

# One IMERG request per region per day covers every LGA in it.
REGIONS: dict[str, tuple[str, ...]] = {
    "nigeria": ("kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "nasarawa", "fct"),
    "ghana": ("ghana",),
    "senegal": ("senegal",),
}

_weights: dict[tuple[str, str], CellWeights] = {}


def region_box(tenants: Iterable[str]) -> tuple[int, int, int, int]:
    """IMERG cell box over every LGA OUTLINE of these tenants (not just the centroids)."""
    return box_for(b.bbox for t in tenants for b in lga_boundaries.for_tenant(t))


def _weights_for(tenant: str, lga: str, geometry: dict) -> CellWeights:
    key = (tenant, lga)
    if key not in _weights:
        _weights[key] = imerg_weights(geometry)
    return _weights[key]


def _as_list(value: Any) -> list | None:
    """JSONB as a list (the driver may hand it over as text)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else None


# ─── measuring ────────────────────────────────────────────────────────────


async def _days_held(session: AsyncSession, start: date, end: date) -> set[date]:
    rows = await session.execute(text("""
        SELECT DISTINCT day FROM rain_measured_daily
         WHERE product = :p AND day BETWEEN :a AND :b
    """), {"p": PRODUCT, "a": start, "b": end})
    return {r[0] for r in rows}


async def _store_day(session: AsyncSession, tenant: str, day: date, arr: RegionArray) -> int:
    """One day's measured rain for every LGA of a tenant. Returns rows offered."""
    rows = []
    for b in lga_boundaries.for_tenant(tenant):
        m = measure(_weights_for(tenant, b.lga, b.geometry), arr)
        if m is None or m.coverage < MIN_COVERAGE:
            continue
        rows.append({
            "t": tenant, "lga": b.lga, "day": day, "p": PRODUCT, "rain": m.rain_mm, "max": m.rain_max_mm,
            "s1": m.wet_share[1], "s10": m.wet_share[10], "s25": m.wet_share[25], "s50": m.wet_share[50],
            "cells": m.cells, "cov": m.coverage, "src": MEASURED_SOURCE,
        })
    if rows:
        await session.execute(text("""
            INSERT INTO rain_measured_daily (
                tenant_id, lga, day, product, rain_mm, rain_max_mm, wet_share_1mm, wet_share_10mm,
                wet_share_25mm, wet_share_50mm, cells, coverage, source
            ) VALUES (:t, :lga, :day, :p, :rain, :max, :s1, :s10, :s25, :s50, :cells, :cov, :src)
            ON CONFLICT (lga, day, product) DO NOTHING
        """), rows)
    return len(rows)


async def _measure_region(client: GpmImergClient, region: str, tenants: list[str], days: list[date],
                          held: dict[str, set[date]], added: dict[str, int]) -> str | None:
    """Fetch and store every day some tenant of this region lacks, newest first.

    Returns a note when days could not be read (they are retried next run).
    ImergAuthError propagates: credentials are global, and 447 identical 401s
    must not read as a dry spell.
    """
    box = region_box(tenants)
    factory = get_session_factory()
    failures = consecutive = 0
    for day in sorted(days, reverse=True):
        todo = [t for t in tenants if day not in held[t]]
        if not todo:
            continue
        try:
            grid = await client.region_grid(lon0=box[0], lon1=box[1], lat0=box[2], lat1=box[3], day=day)
        except ImergAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — one unreadable day; retried next run
            log.warning("forecast check: imerg %s %s skipped: %r", region, day, exc)
            failures += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                return f"{region}: IMERG refused {consecutive} days in a row (last {day}); stopped"
            continue
        consecutive = 0
        if grid is None:
            continue                  # not published yet: normal for the last day or so
        arr = region_array(grid.rows, box, rows_lat0=grid.lat0)
        for t in todo:
            async with factory() as session:
                await set_tenant_schema(session, t)
                added[t] += await _store_day(session, t, day, arr)
                await session.commit()
    return f"{region}: {failures} day(s) unreadable, retried next run" if failures else None


async def measure_days(client: GpmImergClient, days: list[date],
                       tenants: list[str]) -> tuple[dict[str, int], list[str]]:
    """Measure every (region, day) that some tenant does not hold yet.

    Regions are read side by side (three requests at a time, one per region),
    days newest first within each. Returns rows added per tenant and notes.
    """
    added = {t: 0 for t in tenants}
    if not days:
        return added, []
    factory = get_session_factory()
    held: dict[str, set[date]] = {}
    for t in tenants:
        async with factory() as session:
            await set_tenant_schema(session, t)
            held[t] = await _days_held(session, min(days), max(days))
    jobs = [
        _measure_region(client, region, [t for t in members if t in tenants], days, held, added)
        for region, members in REGIONS.items() if any(t in tenants for t in members)
    ]
    notes = await asyncio.gather(*jobs)
    return added, [n for n in notes if n]


# ─── scoring ──────────────────────────────────────────────────────────────


async def _load(session: AsyncSession, start: date) -> tuple[list, list]:
    measured = (await session.execute(text("""
        SELECT lga, day, rain_mm, wet_share_1mm, wet_share_10mm, wet_share_25mm, wet_share_50mm
          FROM rain_measured_daily
         WHERE product = :p AND day >= :start
    """), {"p": PRODUCT, "start": start})).all()
    # Only the 00 UTC runs: their days are the UTC days IMERG measures.
    forecasts = (await session.execute(text("""
        SELECT lga, first_day, rain_ifs_mm, rain_aifs_mm, chance_1mm, chance_10mm, chance_25mm, chance_50mm
          FROM ecmwf_forecast
         WHERE first_day >= :fstart AND EXTRACT(HOUR FROM run_at AT TIME ZONE 'UTC') = 0
    """), {"fstart": start - timedelta(days=LEADS - 1)})).all()
    return measured, [(r[0], r[1], *(_as_list(v) for v in r[2:])) for r in forecasts]


async def summarise_tenant(session: AsyncSession, tenant: str, today: date) -> str:
    """Recompute this tenant's scorecard; append it if anything changed."""
    measured, forecasts = await _load(session, today - timedelta(days=HISTORY_DAYS))
    rec = build_record(measured, forecasts)
    if rec is None:
        return "nothing measured yet"
    s = summarise_record(rec)
    if s["pairs"] == 0:
        return f"{s['lga_days']} LGA-days measured; no stored forecast for them yet"
    result = await session.execute(text("""
        INSERT INTO forecast_check_summary (
            tenant_id, first_day, last_day, days_checked, lga_days, pairs, summary, source
        ) VALUES (:t, :first, :last, :days, :lga_days, :pairs, CAST(:summary AS JSONB), :src)
        ON CONFLICT (last_day, lga_days, pairs) DO NOTHING
    """), {
        "t": tenant, "first": rec.days[0], "last": rec.days[-1], "days": s["days_checked"],
        "lga_days": s["lga_days"], "pairs": s["pairs"], "summary": json.dumps(s), "src": SOURCE,
    })
    verb = "scored" if getattr(result, "rowcount", 1) else "unchanged"
    return f"{verb}: {s['days_checked']} days to {rec.days[-1]}, {s['pairs']} forecast-measurement pairs"


async def _newest_day(session: AsyncSession) -> date | None:
    return (await session.execute(text(
        "SELECT MAX(day) FROM rain_measured_daily WHERE product = :p"), {"p": PRODUCT})).scalar()


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


async def run_forecast_check(tenants: list[str] | None = None, *, trigger: str = "scheduled",
                             today: date | None = None, days: list[date] | None = None) -> dict[str, str]:
    """Measure the recent days, rescore every tenant, record the run. Failures isolated per tenant."""
    started_at = datetime.now(timezone.utc)
    today = today or started_at.date()
    target = sorted(tenants if tenants is not None else PILOT_TENANT_IDS)
    window = days if days is not None else [today - timedelta(days=k) for k in range(1, LOOKBACK_DAYS + 1)]
    added: dict[str, int] = {t: 0 for t in target}
    notes: list[str] = []
    error: str | None = None
    client = GpmImergClient()
    if not client.configured:
        error = "no Earthdata token configured"
    else:
        try:
            added, notes = await measure_days(client, window, target)
        except ImergAuthError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 — recorded per tenant below, never swallowed
            log.exception("forecast check: measuring failed")
            error = f"IMERG read failed: {exc!r}"
        finally:
            client.close()

    out: dict[str, str] = {}
    factory = get_session_factory()
    for tenant in target:
        try:
            async with factory() as session:
                await set_tenant_schema(session, tenant)
                scored = await summarise_tenant(session, tenant, today)
                newest = await _newest_day(session)
                stale = (None if newest is not None and (today - newest).days <= MAX_BEHIND_DAYS
                         else f"newest measured day is {newest or 'none'}; IMERG has not arrived for "
                              f"{MAX_BEHIND_DAYS}+ days")
                await _record_run(session, tenant=tenant, written=added.get(tenant, 0), started_at=started_at,
                                  trigger=trigger, error=error or stale, note="; ".join(notes) or None)
                await session.commit()
            out[tenant] = f"failed: {error or stale}" if (error or stale) else (
                f"{added.get(tenant, 0)} LGA-days measured · {scored}")
        except Exception as exc:  # noqa: BLE001 — isolate per tenant, and record it
            log.exception("forecast check failed tenant=%s", tenant)
            out[tenant] = f"failed: {exc!r}"
            try:
                async with factory() as session:
                    await _record_run(session, tenant=tenant, written=0, started_at=started_at,
                                      trigger=trigger, error=repr(exc))
                    await session.commit()
            except Exception:  # noqa: BLE001 — never mask the real failure
                log.exception("forecast check: could not record failed run tenant=%s", tenant)
    log.info("forecast check: %s", out)
    return out
