"""Whole-LGA land-change scan — every pixel of every LGA, no Processing Units.

WHAT IT REPLACES
----------------
The per-LGA sweeps measure ONE 3 x 3 km box at each LGA centroid: 4,023 km2 of
the 715,731 km2 the 447 pilot LGAs cover (0.56%), and every detection lands on
the same centre point. This reads whole LGAs from the open Sentinel archive and
reports each change at its OWN position.

WHAT IT WRITES, AND WHERE IT DOES NOT
-------------------------------------
Rows go to `land_change_hotspots` (migration 0047) — a SHADOW table that no map
or panel reads. Nothing on the dashboard changes because of this task. Promoting
a hotspot into `alert_events`, which the map does read, is a separate decision
once the shadow rows have been reviewed.

CADENCE
-------
Seasonal, not daily. The comparison needs a rainy-season peak, so it is run
late in the rains and compared with the SAME calendar window a year earlier.
Running it daily would answer nothing new and cost hours of compute.

TENANTS
-------
Only `config.open_archive_tenants` may consume reads — the 8 Nigerian pilots by
default. Ghana and Senegal have boundaries and are configured but held.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone
from uuid import uuid4

import numpy as np
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.warp import transform as rio_transform
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session_factory, set_tenant_schema
from processors.land_change import (
    KIND_BARE,
    KIND_STOPPED,
    Hotspot,
    became_bare,
    find_hotspots,
    stopped_greening,
    usable,
)
from sources import cog_window as cw
from sources import lga_boundaries as lb
from sources import open_archive as oa
from sources.cog_sampler import CogSamplerError

log = logging.getLogger(__name__)

DETECTOR_VERSION = "land_change_v1"
# public.ingestion_runs key. MUST also carry a staleness budget in the API's
# FEED_MAX_AGE_HOURS, or the watchdog reports an unmonitored feed. It is NOT in
# LIVE_SCAN_SOURCES: this is a shadow task and must not appear on the panel.
SOURCE = DETECTOR_VERSION

# The rainy-season window. Both years use the same calendar range: the year
# given more weeks would otherwise have more chances to reach its peak.
WET_START_MD = (7, 1)
WET_END_CAP_MD = (10, 15)

# Dates sampled per season. Peak greenness needs several cloud-free looks;
# beyond a dozen the peak stops moving and the reads are wasted.
MAX_DATES = 12
# Scene-level cloud gate. Pixel-level cloud is masked from SCL regardless, so
# this only avoids spending reads on scenes that are almost entirely cloud.
CLOUD_LT = 60
# Concurrent date-reads. Reads are network-bound; this is the main lever on
# wall-clock. Each in-flight date holds three arrays, so it also bounds memory.
CONCURRENCY = 6
# The archive is free and has no SLA. Reads are retried this many times with a
# doubling pause before the date is given up on.
READ_ATTEMPTS = 4
READ_BACKOFF_S = 2.0

BAD_SCL = (0, 1, 3, 6, 8, 9, 10, 11)   # nodata, saturated, shadow, water, clouds, cirrus, snow
S2_RED, S2_NIR, S2_SCL = "B04", "B08", "SCL"
# Sentinel-2 L2A carries a +1000 offset from processing baseline 04.00 (2022).
BOA_OFFSET = 1000.0


def wet_window(year: int, end: date) -> tuple[datetime, datetime]:
    """The rainy-season window for `year`, ending no later than `end`'s date."""
    start = date(year, *WET_START_MD)
    cap = date(year, *WET_END_CAP_MD)
    stop = min(date(year, end.month, end.day), cap)
    if stop <= start:
        stop = cap
    return (datetime.combine(start, time.min, timezone.utc),
            datetime.combine(stop, time.max, timezone.utc))


def _spread(days: list[date], n: int) -> list[date]:
    days = sorted(days)
    if len(days) <= n:
        return days
    return [days[i] for i in np.linspace(0, len(days) - 1, n).round().astype(int)]


async def _read_once(href, grid, rs):
    """One read, retried through the archive's transient failures.

    Planetary Computer is free and unmetered and answers 503 under load. A
    single hiccup must not cost an LGA an hour of reads, so each read gets a
    few widening attempts before it is given up on.
    """
    for attempt in range(1, READ_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(cw.read_on_grid, href, grid, resampling=rs)
        except (CogSamplerError, RasterioIOError) as exc:
            if attempt == READ_ATTEMPTS:
                raise
            wait = READ_BACKOFF_S * 2 ** (attempt - 1)
            log.warning("land change: read failed (%s), retry %d/%d in %.0fs",
                        type(exc).__name__, attempt, READ_ATTEMPTS, wait)
            await asyncio.sleep(wait)


async def _read(scenes, asset, grid, rs=Resampling.average):
    """First scene that covers each pixel wins; frames of one pass are merged."""
    out = None
    for s in scenes:
        if asset not in s.assets:
            continue
        href = await oa.signed_href(oa.S2_L2A, s.assets[asset])
        arr = await _read_once(href, grid, rs)
        out = arr if out is None else np.where(np.isnan(out), arr, out)
    return out


async def _ndvi_for_day(scenes, grid, sem: asyncio.Semaphore):
    """NDVI for one day, or None if the archive would not give it up.

    A date dropped here is not a silent hole: it lowers that pixel's observation
    count, and `usable()` refuses to judge a pixel both seasons did not see
    often enough. Losing a date is safe; losing the LGA is not.
    """
    async with sem:
        try:
            red = await _read(scenes, S2_RED, grid)
            nir = await _read(scenes, S2_NIR, grid)
            scl = await _read(scenes, S2_SCL, grid, Resampling.mode)
        except (CogSamplerError, RasterioIOError) as exc:
            log.warning("land change: dropping %s — archive unavailable (%s)",
                        scenes[0].datetime.date(), type(exc).__name__)
            return None
    if red is None or nir is None:
        return None
    r = np.clip((red - BOA_OFFSET) / 1e4, 0, None)
    n = np.clip((nir - BOA_OFFSET) / 1e4, 0, None)
    ndvi = (n - r) / np.maximum(n + r, 1e-6)
    if scl is not None:
        ndvi[np.isin(scl, BAD_SCL)] = np.nan
    return ndvi.astype("float32")


async def peak_greenness(bbox, grid, start: datetime, end: datetime):
    """Highest NDVI each pixel reached in the window, and how often it was seen.

    A running maximum, so memory does not grow with the number of dates — the
    naive stack-then-median ran a 6.6M-pixel LGA out of 1 GB.
    """
    scenes = await oa.search(oa.S2_L2A, bbox, start, end,
                             query={"eo:cloud_cover": {"lt": CLOUD_LT}})
    by_day: dict[date, list] = {}
    for s in scenes:
        by_day.setdefault(s.datetime.date(), []).append(s)
    days = _spread(list(by_day), MAX_DATES)

    shape = (grid.height, grid.width)
    peak = np.full(shape, np.nan, dtype="float32")
    seen = np.zeros(shape, dtype="uint8")
    if not days:
        return peak, seen, []

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [asyncio.create_task(_ndvi_for_day(by_day[d], grid, sem)) for d in days]
    for done in asyncio.as_completed(tasks):
        ndvi = await done
        if ndvi is None:
            continue
        seen += np.isfinite(ndvi).astype("uint8")
        peak = np.fmax(peak, ndvi)
    return peak, seen, [str(d) for d in days]


async def scan_lga(boundary, end: date, year: int) -> tuple[list[Hotspot], float, dict]:
    """One LGA: both seasons' peak greenness, then the hotspots between them."""
    grid = cw.lga_grid(boundary.bbox)
    inside = cw.outline_mask(grid, boundary.geometry)
    prev_win = wet_window(year - 1, end)
    now_win = wet_window(year, end)
    prev, n_prev, prev_dates = await peak_greenness(boundary.bbox, grid, *prev_win)
    now, n_now, now_dates = await peak_greenness(boundary.bbox, grid, *now_win)

    ok = usable(inside, prev, now, n_prev, n_now)
    inside_n = int(inside.sum())
    observed = float(ok.sum()) / inside_n if inside_n else 0.0

    def to_lonlat(x: float, y: float) -> tuple[float, float]:
        lon, lat = rio_transform(grid.crs, "EPSG:4326", [x], [y])
        return lon[0], lat[0]

    hotspots: list[Hotspot] = []
    for kind, mask in ((KIND_STOPPED, stopped_greening(prev, now, ok)),
                       (KIND_BARE, became_bare(prev, now, ok))):
        hotspots += find_hotspots(mask, kind=kind, transform=grid.transform,
                                  to_lonlat=to_lonlat, prev=prev, now=now)
    meta = {"prev_dates": prev_dates, "now_dates": now_dates,
            "window": (now_win[0].date(), now_win[1].date())}
    return hotspots, observed, meta


async def _write(session: AsyncSession, *, tenant: str, lga: str, year: int,
                 hotspots: list[Hotspot], observed: float, window) -> None:
    for h in hotspots:
        await session.execute(text("""
            INSERT INTO land_change_hotspots (
                tenant_id, lga, kind, location, lon, lat, area_ha,
                peak_prev, peak_now, season_year, prev_season_year,
                window_start, window_end, lga_observed_fraction, detector_version
            ) VALUES (
                :t, :lga, :kind, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :lon, :lat,
                :area, :prev, :now, :yr, :pyr, :ws, :we, :obs, :dv
            )
            ON CONFLICT (lga, season_year, kind, lon, lat) DO UPDATE SET
                area_ha = EXCLUDED.area_ha,
                peak_prev = EXCLUDED.peak_prev,
                peak_now = EXCLUDED.peak_now,
                lga_observed_fraction = EXCLUDED.lga_observed_fraction,
                detected_at = NOW()
        """), {
            "t": tenant, "lga": lga, "kind": h.kind, "lon": h.lon, "lat": h.lat,
            "area": h.area_ha, "prev": h.peak_prev, "now": h.peak_now,
            "yr": year, "pyr": year - 1, "ws": window[0], "we": window[1],
            "obs": round(observed, 4), "dv": DETECTOR_VERSION,
        })


async def _record_run(session: AsyncSession, *, tenant: str, written: int,
                      started_at: datetime, trigger: str, error: str | None = None) -> None:
    """Stamp public.ingestion_runs so the watchdog can see this task at all."""
    await session.execute(text("""
        INSERT INTO public.ingestion_runs (
            id, source, tenant_id, trigger, started_at, finished_at,
            status, records_ingested, error_message, dry_run
        ) VALUES (
            :id, :source, :tenant, :trigger, :started_at, NOW(),
            :status, :written, :error, FALSE
        )
    """), {
        "id": uuid4(), "source": SOURCE, "tenant": tenant, "trigger": trigger,
        "started_at": started_at, "written": written,
        "status": "failed" if error else "succeeded",
        "error": error[:500] if error else None,
    })


async def _persist(factory, *, tenant: str, lga: str, year: int,
                   hotspots: list[Hotspot], observed: float, window) -> None:
    """Store one LGA's hotspots in a session of its own.

    A whole-Nigeria pass runs for hours. Holding one connection open across it
    invites a dropped socket to discard every LGA already scanned, so each LGA
    commits alone and partial progress survives.
    """
    async with factory() as session:
        await set_tenant_schema(session, tenant)
        await _write(session, tenant=tenant, lga=lga, year=year,
                     hotspots=hotspots, observed=observed, window=window)
        await session.commit()


async def _record(factory, **kw) -> None:
    async with factory() as session:
        await _record_run(session, **kw)
        await session.commit()


async def run_land_change_scan(
    tenants: list[str] | None = None,
    *,
    lgas: list[str] | None = None,
    end: date | None = None,
    max_lgas: int | None = None,
    write: bool = True,
    trigger: str = "manual",
) -> dict[str, str]:
    """Scan whole LGAs for land that stopped greening. Failures isolated per tenant."""
    started_at = datetime.now(timezone.utc)
    end = end or datetime.now(timezone.utc).date()
    year = end.year
    targets = tenants if tenants is not None else oa.active_tenants()
    held = oa.held_tenants()
    if held:
        log.info("land change: %d tenant(s) configured but held: %s", len(held), held)

    factory = get_session_factory() if write else None
    out: dict[str, str] = {}
    for tenant in targets:
        boundaries = [b for b in lb.for_tenant(tenant)
                      if lgas is None or b.lga in lgas]
        if max_lgas:
            boundaries = boundaries[:max_lgas]
        if not boundaries:
            out[tenant] = "no LGA boundaries"
            continue
        found = scanned = 0
        thin: list[str] = []
        failed: list[str] = []
        try:
            for b in boundaries:
                try:
                    hotspots, observed, meta = await scan_lga(b, end, year)
                except Exception as exc:  # noqa: BLE001 — isolate per LGA
                    # A whole-Nigeria pass is hours long and reads a free
                    # archive. One LGA the catalogue will not serve must not
                    # abandon the two hundred behind it.
                    failed.append(b.lga)
                    log.exception("land change: %s/%s failed: %r", tenant, b.lga, exc)
                    continue
                scanned += 1
                if observed < 0.5:
                    # Say so rather than reporting "nothing found" for an LGA
                    # the clouds hid.
                    thin.append("%s %.0f%%" % (b.lga, 100 * observed))
                if write and hotspots:
                    await _persist(factory, tenant=tenant, lga=b.lga, year=year,
                                   hotspots=hotspots, observed=observed,
                                   window=meta["window"])
                found += len(hotspots)
                log.info("land change: %s/%s %d hotspot(s), %.0f%% observed "
                         "(%d prev / %d now dates)", tenant, b.lga, len(hotspots),
                         100 * observed, len(meta["prev_dates"]), len(meta["now_dates"]))
                for h in hotspots:
                    # Coordinates in the log, so a run can be checked against
                    # imagery without a database — including a dry rehearsal
                    # and a one-shot task read back from CloudWatch. These are
                    # land patches of a hectare or more, not people.
                    log.info("land change:   %-16s %8.5f,%8.5f %7.1f ha "
                             "peak %.2f -> %.2f", h.kind, h.lat, h.lon,
                             h.area_ha, h.peak_prev, h.peak_now)
            if write:
                await _record(factory, tenant=tenant, written=found,
                              started_at=started_at, trigger=trigger)
            detail = f"{found} hotspot(s) across {scanned} LGA(s)"
            if thin:
                detail += f"; {len(thin)} poorly observed [{', '.join(thin[:3])}]"
            if failed:
                # Never let unreadable LGAs read as quiet ones.
                detail += f"; {len(failed)} UNREAD [{', '.join(failed[:3])}]"
            out[tenant] = detail
        except Exception as exc:  # noqa: BLE001 — isolate per tenant
            out[tenant] = f"failed after {scanned} LGA(s): {exc!r}"
            log.exception("land change failed tenant=%s", tenant)
            if write:
                try:
                    await _record(factory, tenant=tenant, written=found,
                                  started_at=started_at, trigger=trigger,
                                  error=repr(exc))
                except Exception:  # noqa: BLE001 — never mask the real failure
                    log.exception("land change: could not record failed run tenant=%s", tenant)
    log.info("land change: %s", out)
    return out
