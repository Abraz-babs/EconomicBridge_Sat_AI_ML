"""Daily storm scan — every LGA, every pilot, from half-hourly rainfall.

WHAT IT IS
----------
Reconstructs storms from IMERG half-hourly rate and judges each against that
LGA's own intensity record. Runs across all 10 pilots and all 447 LGAs in one
pass, because a slice is ONE request per REGION regardless of how many LGAs sit
inside it — full statewide coverage costs the same as sampling a single point.

That is the opposite of the CDSE-backed sweeps, where each LGA costs its own
Processing Units and coverage has to rotate on a 12-day revisit. Here there is
no reason to rotate, so nothing does.

WHY IT EXISTS
-------------
Abuja flooded on 2026-08-30/31 and the platform said nothing. Not a threshold
problem: the daily product accumulates over a calendar day in UTC, the storm
ran 21:00-00:30 WAT, and it was split across two granules that each looked
ordinary. See processors/storm_event.py for the measured detail.

WHAT IT CLAIMS, AND WHAT IT DOES NOT
------------------------------------
It reports STORMS — what fell, how fast, for how long, and how that compares
with the same place's own record. It does NOT claim a flood. Whether rainfall
floods somewhere depends on drainage, soil saturation, slope and how much
ground is concrete, none of which we observe. The Kebbi 2024 backtest scored
0 of 11 on a detector that confused "a signal is present" with "a flood
happened"; the naming here is deliberate.

Percentiles are reported with the sample size behind them. A 99th percentile
over nine days of history is not a 99th percentile, and the row says so rather
than letting a reader assume.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.storm_event import find_storms, window_maxima
from sources.gpm_imerg_halfhourly import ImergHalfHourlyClient
from tasks.encroachment_detector import select_lgas
from tasks.rainstorm_scan import REGIONS, TENANT_REGION

log = logging.getLogger(__name__)

DETECTOR_VERSION = "storm_scan_v1"
# public.ingestion_runs key. MUST also be listed in the API router's
# LIVE_SCAN_SOURCES, or this feed runs daily and the dashboard never shows
# it — the exact way the IMERG rainfall advisory stayed invisible for
# weeks after it shipped. A feed nobody can see is not a feed.
SOURCE = DETECTOR_VERSION

# Trailing window fetched each run. 36h covers a full night either side of the
# scan, so a storm that began yesterday evening and ended after midnight is
# seen whole — which is the entire point.
WINDOW_HOURS = 36

# A full UTC day of half-hourly slices. The intensity record is per DAY, so
# coverage is judged against a day and not against the scan's wider window.
SLICES_PER_DAY = 48

# The Late run trails real time; asking for the last couple of hours returns
# 404s that are not errors. Start the window slightly back rather than logging
# noise about granules that simply are not published yet.
LATENCY_HOURS = 5

# Minimum days of intensity record before a percentile is worth reporting.
# Below this the number is stored (it is a real observation) but no severity is
# assigned, because "highest in 4 days" should not look like "highest in 90".
MIN_BASELINE_DAYS = 21

# Percentile bands. Deliberately relative, not absolute mm/hr: IMERG
# underestimates intense convection over an ~11 km cell, so an absolute
# threshold calibrated on gauge data under-fires everywhere. What survives that
# bias is how a place compares with ITSELF.
SEV_CRITICAL = 99.0
SEV_HIGH = 97.0
SEV_MEDIUM = 90.0

# A rank-based percentile over n prior observations cannot express anything
# finer than 1/n. With 25 days of record the steps are 4 percentage points
# apart, so p97 and p99 are the SAME observation - "higher than everything I
# have seen" - and the band between them is not merely rare, it is
# unreachable. Measured on the first full backfill: 67 critical, 58 medium,
# and exactly 0 high across all ten pilots. A band that can never be assigned
# is a label that means nothing.
#
# So a band is only offered when the sample can resolve it. Below that the
# severity is capped, not suppressed: the storm is still reported, and
# reported as what the evidence supports. "The heaviest hour in the 25 days on
# record here" is a true and useful statement. "Critical, 99th percentile" is
# not, on 25 days.
MIN_DAYS_FOR_CRITICAL = 100   # 1/100 = 1% resolves p99
MIN_DAYS_FOR_HIGH = 34        # 1/34  ~ 2.9% resolves p97
MIN_DAYS_FOR_MEDIUM = 10      # 1/10  = 10% resolves p90


def _degrees(region: str) -> tuple[float, float, float, float]:
    """Region grid indices -> degree bounds, padded by one cell.

    Derived from REGIONS in rainstorm_scan so the two feeds cover exactly the
    same ground and one place owns the geography.
    """
    lon0, lon1, lat0, lat1 = REGIONS[region]
    return (
        lon0 * 0.1 - 180.0 - 0.1,
        lon1 * 0.1 - 180.0 + 0.1,
        lat0 * 0.1 - 90.0 - 0.1,
        lat1 * 0.1 - 90.0 + 0.1,
    )


@dataclass(frozen=True, slots=True)
class LgaStorm:
    lga: str
    lon: float
    lat: float
    storm: object                     # StormEvent
    max_1h: float
    max_3h: float
    max_6h: float


def _severity(pct_1h: float | None, pct_3h: float | None,
              baseline_days: int) -> str | None:
    """Severity from the better of the two percentiles, or None.

    None means "recorded, not rated" — either too little history, or the storm
    is unremarkable for this place. A storm that is ordinary here is still worth
    keeping in the intensity record; it is not worth alerting on.

    Severity is also CAPPED by what the sample can resolve, so a shallow record
    yields "medium" rather than a "critical" the evidence cannot support. The
    cap loosens by itself as the record deepens; nothing has to be re-tuned.
    """
    if baseline_days < MIN_BASELINE_DAYS:
        return None
    best = max([p for p in (pct_1h, pct_3h) if p is not None], default=None)
    if best is None:
        return None
    if best >= SEV_CRITICAL and baseline_days >= MIN_DAYS_FOR_CRITICAL:
        return "critical"
    if best >= SEV_HIGH and baseline_days >= MIN_DAYS_FOR_HIGH:
        return "high"
    if best >= SEV_MEDIUM and baseline_days >= MIN_DAYS_FOR_MEDIUM:
        return "medium"
    return None


async def _percentile(
    session: AsyncSession, *, lga: str, column: str, value: float,
) -> tuple[float | None, int]:
    """Where `value` sits in this LGA's own record, and how deep that record is.

    Compares against the LGA's history EXCLUDING today, so a storm is never
    ranked against itself — the same leave-one-out discipline the drought
    climatology uses.
    """
    row = (await session.execute(text(
        f"""
        SELECT COUNT(*) AS n,
               COUNT(*) FILTER (WHERE {column} < :v) AS below
          FROM storm_intensity_daily
         WHERE lga = :lga AND day < CURRENT_DATE AND {column} IS NOT NULL
        """
    ), {"lga": lga, "v": value})).mappings().first()
    n = int(row["n"] or 0)
    if n == 0:
        return None, 0
    return round(100.0 * int(row["below"] or 0) / n, 1), n


async def _record_intensity(
    session: AsyncSession, *, tenant: str, lga: str, day: date,
    accum: dict[int, float], peak_mm_hr: float, seen: int, expected: int,
) -> None:
    """Append ONE UTC DAY's worst accumulations for this LGA.

    This is what grows the baseline, and the day it is filed under is the day
    the rain actually fell - not the day the scan ran.

    The scan reads a 36h window so a storm that crosses midnight is seen whole,
    which means consecutive runs overlap by twelve hours. Filing everything
    under "today" would enter one storm into two different days of the record,
    inflating the upper tail with a day that never happened and making every
    later storm look ordinary by comparison. Filing by the day of the rain
    makes the write idempotent instead: tomorrow's overlapping window
    recomputes the same day and GREATEST leaves it unchanged.

    It also makes live rows and bootstrap rows the same measurement. They land
    in one distribution, so they had better be measuring one thing.
    """
    await session.execute(text("""
        INSERT INTO storm_intensity_daily (
            tenant_id, lga, day, max_1h_mm, max_3h_mm, max_6h_mm,
            peak_mm_hr, slices_seen, slices_expected
        ) VALUES (
            :t, :lga, :day, :h1, :h3, :h6, :peak, :seen, :expected
        )
        ON CONFLICT (lga, day) DO UPDATE SET
            max_1h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_1h_mm, 0), EXCLUDED.max_1h_mm),
            max_3h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_3h_mm, 0), EXCLUDED.max_3h_mm),
            max_6h_mm  = GREATEST(COALESCE(storm_intensity_daily.max_6h_mm, 0), EXCLUDED.max_6h_mm),
            peak_mm_hr = GREATEST(COALESCE(storm_intensity_daily.peak_mm_hr, 0), EXCLUDED.peak_mm_hr),
            slices_seen = GREATEST(storm_intensity_daily.slices_seen, EXCLUDED.slices_seen)
    """), {
        "t": tenant, "lga": lga, "day": day,
        "h1": accum.get(1, 0.0), "h3": accum.get(3, 0.0),
        "h6": accum.get(6, 0.0),
        "peak": peak_mm_hr, "seen": seen, "expected": expected,
    })


async def _record_event(
    session: AsyncSession, *, tenant: str, s: LgaStorm,
    pct_1h: float | None, pct_3h: float | None, baseline_days: int,
    severity: str | None,
) -> None:
    e = s.storm
    await session.execute(text("""
        INSERT INTO storm_events (
            tenant_id, lga, lon, lat, started_at, ended_at, peak_at,
            crosses_midnight_utc, peak_mm_hr, total_mm,
            max_1h_mm, max_3h_mm, max_6h_mm, duration_h,
            percentile_1h, percentile_3h, baseline_days, severity,
            detector_version
        ) VALUES (
            :t, :lga, :lon, :lat, :start, :end, :peak_at,
            :crosses, :peak, :total, :h1, :h3, :h6, :dur,
            :p1, :p3, :bdays, :sev, :dver
        )
        ON CONFLICT (lga, started_at) DO NOTHING
    """), {
        "t": tenant, "lga": s.lga, "lon": s.lon, "lat": s.lat,
        "start": e.start, "end": e.end, "peak_at": e.peak_at,
        "crosses": e.crosses_midnight_utc, "peak": e.peak_mm_hr,
        "total": e.total_mm, "h1": s.max_1h, "h3": s.max_3h, "h6": s.max_6h,
        "dur": e.duration_h, "p1": pct_1h, "p3": pct_3h,
        "bdays": baseline_days, "sev": severity, "dver": DETECTOR_VERSION,
    })


async def _record_run(
    session: AsyncSession, *, tenant: str, written: int,
    started_at: datetime, trigger: str, error: str | None = None,
) -> None:
    """Stamp public.ingestion_runs so the panel can prove the scan is live.

    Recorded on EVERY outcome including "no slices retrieved", which is a
    failure and is written as one. A scan that reads nothing must not leave the
    same trace as a scan that read a dry day — the panel would report
    continuous monitoring over a blind feed.
    """
    # Columns are records_ingested / error_message / dry_run (migration 0004).
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


async def scan_region(
    client: ImergHalfHourlyClient, http: httpx.AsyncClient, region: str,
    *, end: datetime, hours: int,
) -> tuple[list, int]:
    """Fetch one region's trailing window. Returns (grids, expected slices)."""
    lon_min, lon_max, lat_min, lat_max = _degrees(region)
    grids = await client.window(
        lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max,
        end=end, hours=hours,
    )
    return grids, hours * 2


async def run_storm_scan(
    tenants: list[str] | None = None, *, hours: int = WINDOW_HOURS,
    trigger: str = "scheduled",
) -> dict[str, str]:
    """Scan every pilot for storms. Failures isolated per tenant.

    One region fetch serves every tenant inside it, so the cost is three
    windows regardless of how many tenants or LGAs are scanned.
    """
    client = ImergHalfHourlyClient()
    if not client.configured:
        log.warning("storm scan: no EARTHDATA_TOKEN — skipped")
        return {}

    started_at = datetime.now(timezone.utc)
    target = sorted(tenants if tenants is not None else PILOT_TENANT_IDS)
    end = datetime.now(timezone.utc) - timedelta(hours=LATENCY_HOURS)
    # No "today" here on purpose: intensity rows are filed under the day the
    # rain fell, read off each slice, never under the day the scan ran.

    needed = {TENANT_REGION.get(t) for t in target} - {None}
    windows: dict[str, tuple[list, int]] = {}
    out: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0),
                                 follow_redirects=True) as http:
        for region in sorted(needed):
            try:
                windows[region] = await scan_region(
                    client, http, region, end=end, hours=hours)
                grids, expected = windows[region]
                log.info("storm scan: region %s %d/%d slices",
                         region, len(grids), expected)
            except Exception as exc:  # noqa: BLE001 — one region must not stop the rest
                log.exception("storm scan: region %s failed", region)
                windows[region] = ([], hours * 2)
                out[f"region:{region}"] = f"failed: {exc!r}"

        factory = get_session_factory()
        for tenant in target:
            region = TENANT_REGION.get(tenant)
            grids, expected = windows.get(region, ([], hours * 2))
            if not grids:
                # No slices is NOT a calm day. Say which it was, the same
                # distinction the other scans draw between "not checked" and
                # "no signal".
                msg = "not scanned (no half-hourly slices retrieved)"
                out[tenant] = msg
                async with factory() as session:
                    await _record_run(
                        session, tenant=tenant, written=0,
                        started_at=started_at, trigger=trigger, error=msg)
                    await session.commit()
                continue
            try:
                async with factory() as session:
                    await set_tenant_schema(session, tenant)
                    stormy = rated = 0
                    for g in select_lgas(tenant, full=True):
                        series = []
                        for grid in grids:
                            v = grid.sample_max(g["lon"], g["lat"])
                            if v is not None:
                                series.append((grid.at, v))
                        events = find_storms(series)
                        if not events:
                            continue

                        # BASELINE: one row per UTC day the rain fell on,
                        # measured from that day's own slices. The window spans
                        # parts of up to three days; a partly-covered day is
                        # written anyway because GREATEST can only raise a row,
                        # never lower one, and the following run sees the rest.
                        by_day: dict[date, list] = {}
                        for at, rate in series:
                            by_day.setdefault(at.date(), []).append((at, rate))
                        for d, day_series in by_day.items():
                            wm = window_maxima(day_series)
                            if wm is None:
                                continue
                            day_accum, day_peak = wm
                            await _record_intensity(
                                session, tenant=tenant, lga=g["lga"], day=d,
                                accum=day_accum, peak_mm_hr=day_peak,
                                seen=len(day_series), expected=SLICES_PER_DAY)

                        # RATING: the storm itself, on its own accumulations.
                        e = max(events, key=lambda x: x.accum.get(1, 0.0))
                        s = LgaStorm(
                            lga=g["lga"], lon=g["lon"], lat=g["lat"], storm=e,
                            max_1h=e.accum.get(1, 0.0),
                            max_3h=e.accum.get(3, 0.0),
                            max_6h=e.accum.get(6, 0.0),
                        )
                        p1, n1 = await _percentile(
                            session, lga=s.lga, column="max_1h_mm", value=s.max_1h)
                        p3, n3 = await _percentile(
                            session, lga=s.lga, column="max_3h_mm", value=s.max_3h)
                        bdays = max(n1, n3)
                        sev = _severity(p1, p3, bdays)
                        if sev is not None:
                            await _record_event(
                                session, tenant=tenant, s=s, pct_1h=p1,
                                pct_3h=p3, baseline_days=bdays, severity=sev)
                            rated += 1
                        stormy += 1
                    await _record_run(
                        session, tenant=tenant, written=stormy,
                        started_at=started_at, trigger=trigger)
                    await session.commit()
                    out[tenant] = (
                        f"{rated} storm event(s) / {stormy} LGA(s) with rain "
                        f"({len(grids)}/{expected} slices)"
                    )
            except Exception as exc:  # noqa: BLE001 — isolate per tenant
                out[tenant] = f"failed: {exc!r}"
                log.exception("storm scan failed tenant=%s", tenant)
                # A fresh session: the one that raised is poisoned, and the
                # failure has to be recorded or the feed reads as healthy.
                try:
                    async with factory() as session:
                        await _record_run(
                            session, tenant=tenant, written=0,
                            started_at=started_at, trigger=trigger,
                            error=repr(exc))
                        await session.commit()
                except Exception:  # noqa: BLE001 — never mask the real failure
                    log.exception("storm scan: could not record failed run "
                                  "tenant=%s", tenant)

    log.info("storm scan: %s", out)
    return out
