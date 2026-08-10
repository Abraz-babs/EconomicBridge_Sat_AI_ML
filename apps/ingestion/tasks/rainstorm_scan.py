"""Scheduled per-LGA exceptional-rainfall scan (flood-risk advisory).

Runs daily at 08:00 UTC — see scheduler.py. (This docstring used to say it was
deliberately unwired; that stopped being true when the feed went live and the
line was left behind. Wiring is in scheduler.py, not here.)

Originally built as rainstorm early warning. Validation on real IMERG data
(2026-07-26) proved daily rainfall cannot see wind-damage storms: Riyom sat at
p72 of its own distribution on the day 100+ houses fell, Bassa at p25, Shendam
at p45. Mokwa (151 deaths) reached only p93 — its flood came from a failed
railway embankment, not exceptional rain. Full evidence in
processors/rainstorm_signal.py.

So this emits `flood`, not `rainstorm`: exceptional rainfall for a given LGA is
a genuine flood precursor (a volume-driven hazard IMERG can see), while roof
damage from a convective downburst is not something this instrument observes.
Calling these rows `rainstorm` would repeat exactly the mislabelling this whole
change set removed.

Design notes
------------
* **Every LGA, every run.** Unlike the CDSE sweeps there is no processing-unit
  budget here — IMERG is a NASA public archive and we fetch a ~3x3 cell subset,
  so a full sweep is cheap. No rolling 1/N slice, no staleness between revisits.
* **Idempotent per run.** Prior `rainstorm_scan_v1` rows are replaced, exactly
  like shockguard_scan_v1, so the feed reflects the current window rather than
  accumulating duplicates of the same storm.
* **Warning, not damage.** Rows are model-derived (`requires_human_review=True`)
  and their metrics state plainly that IMERG's ~11 km cell cannot resolve a
  settlement. Damage counts in the register stay sourced from NEMA/press.
* **Auth failure is loud.** An ImergAuthError aborts the whole sweep instead of
  being swallowed per-LGA — 447 identical 401s in the log helps nobody, and a
  silent no-op would look exactly like "no storms", which is the one thing a
  warning system must never fake.
* **A partial window is refused, not used.** MIN_COVERAGE / MAX_OBSERVED_AGE_DAYS
  below. The same principle: a baseline with a month torn out of it cannot say
  what is exceptional, so the run is recorded failed rather than answering
  anyway.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.rainstorm_signal import RainstormSignal, compute_rainstorm
from sources.gpm_imerg import GpmImergClient, ImergAuthError, RegionGrid
from tasks.encroachment_detector import select_lgas

log = logging.getLogger(__name__)

SOURCE = "rainstorm_scan_v1"
DETECTOR = "imerg_extreme_rainfall"
DETECTOR_VERSION = "1.0.0"

# Days of history per LGA. A p99 wet-day percentile needs MIN_WET_DAYS (20)
# wet days behind it; at roughly half of rainy-season days being wet, 90 days
# is the smallest window that reliably clears that bar.
#
# Fetch strategy: pulling each LGA point separately cost one request each —
# 447 LGAs x 90 days is ~40,000 requests per run, which is not a feed, it is
# an outage. We now pull one REGION grid per day and sample every LGA out of
# it, so 3 requests cover all 447 LGAs for a day and a full 90-day baseline is
# ~270 requests (~15 min).
BASELINE_DAYS = 90

# Regional grids as IMERG cell indices (0.1 deg), derived from the pilot LGA
# centroids with a small margin. Kept explicit rather than recomputed per run
# so request size stays predictable and reviewable: Nigeria ~4.5k cells
# (~57 KB), Ghana ~3k, Senegal ~2.5k.
REGIONS: dict[str, tuple[int, int, int, int]] = {
    # name: (lon0, lon1, lat0, lat1)
    "nigeria": (1836, 1903, 966, 1031),
    "ghana": (1767, 1812, 947, 1012),
    "senegal": (1623, 1683, 1023, 1064),
}
TENANT_REGION: dict[str, str] = {
    "kebbi": "nigeria", "benue": "nigeria", "plateau": "nigeria",
    "kaduna": "nigeria", "niger": "nigeria", "zamfara": "nigeria",
    "nasarawa": "nigeria", "fct": "nigeria",
    "ghana": "ghana", "senegal": "senegal",
}
# IMERG Late publishes ~1 day behind; asking for today returns nothing.
LATENCY_DAYS = 1

# ─── How much of the window has to arrive before we may judge a day ────────
# Learned the hard way on 2026-07-27: a GES DISC reprocessing window refused 34
# consecutive days (2026-06-18 to 2026-07-21) and the sweep carried on with the
# remaining 55 as though they were the whole record. A contiguous hole is the
# worst kind — it lands in peak wet season, removes the wettest days from the
# distribution, drags the p99 threshold down and manufactures advisories.
#
# 0.75 of 90 days is 68, comfortably clear of the 20 wet days a percentile
# needs while still rejecting a window with a month torn out of it.
MIN_COVERAGE = 0.75

# How far behind `end` the newest retrieved day may be. An advisory asserts
# something about NOW; if the most recent day we hold is a week old, the claim
# is not one we can support no matter how deep the baseline is.
MAX_OBSERVED_AGE_DAYS = 3

# Give up on a region after this many consecutive days refuse us. Each day now
# retries with backoff across three minor versions, so an archive-wide outage
# would otherwise spend ~45 s per day x 90 days x 3 regions before concluding
# what the first ten days already showed. Only genuine failures count — a day
# that simply is not published yet returns None and is not a failure.
MAX_CONSECUTIVE_FAILURES = 10


@dataclass(frozen=True)
class RegionWindow:
    """One region's fetched baseline, plus whether it may be used at all."""

    region: str
    grids: list[RegionGrid]           # oldest first
    requested_days: int
    end: date

    @property
    def coverage(self) -> float:
        if self.requested_days <= 0:
            return 0.0
        return len(self.grids) / self.requested_days

    @property
    def newest(self) -> date | None:
        return self.grids[-1].day if self.grids else None

    def unusable_reason(self) -> str | None:
        """Why this window must not produce advisories, or None if it may."""
        if not self.grids:
            return "no IMERG days retrieved"
        if self.coverage < MIN_COVERAGE:
            return (
                f"only {len(self.grids)}/{self.requested_days} IMERG days "
                f"retrieved ({self.coverage:.0%}) — too little of the record "
                "to say what is exceptional here"
            )
        newest = self.newest
        assert newest is not None            # grids non-empty, checked above
        behind = (self.end - newest).days
        if behind > MAX_OBSERVED_AGE_DAYS:
            return (
                f"newest IMERG day is {newest}, {behind} days behind {self.end}"
                " — an advisory from it would not be about now"
            )
        return None


def _zone_label(lga: str, sig: RainstormSignal) -> str:
    return (
        f"Exceptional rainfall over {lga}: {sig.rain_mm:.0f} mm/day — "
        f"p{sig.percentile:.0f} for this LGA (its p99 day is "
        f"{sig.threshold_mm:.0f} mm, median wet day {sig.baseline_mm:.0f} mm)"
    )


async def _replace_prior(session: AsyncSession) -> None:
    await session.execute(
        text("DELETE FROM shock_events WHERE source = :s"), {"s": SOURCE}
    )


async def _insert(
    session: AsyncSession, *, tenant: str, lga: str, lon: float, lat: float,
    sig: RainstormSignal, observed: date,
) -> None:
    metrics = dict(sig.as_metrics())
    metrics["observed_date"] = observed.isoformat()
    await session.execute(text("""
        INSERT INTO shock_events (
            tenant_id, event_type, detector_name, detector_version,
            severity, confidence, confidence_band, requires_human_review,
            projected_onset_hours, affected_area_km2, population_at_risk,
            location, lga, zone_name, metrics, source
        ) VALUES (
            :tenant_id, 'flood', :detector, :dver,
            :severity, :confidence, :band, TRUE,
            NULL, NULL, NULL,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            :lga, :zone, CAST(:metrics AS JSONB), :source
        )
    """), {
        "tenant_id": tenant, "detector": DETECTOR, "dver": DETECTOR_VERSION,
        "severity": sig.severity, "confidence": sig.confidence,
        "band": sig.confidence_band, "lon": lon, "lat": lat, "lga": lga,
        "zone": _zone_label(lga, sig), "metrics": json.dumps(metrics),
        "source": SOURCE,
    })


async def _record_run(
    session: AsyncSession, *, tenant: str, written: int,
    started_at: datetime, trigger: str, error: str | None = None,
) -> None:
    """Stamp public.ingestion_runs so the panel can prove the scan is live even
    when (correctly) no storm is flagged."""
    # Column names are records_ingested / error_message / dry_run (migration
    # 0004) — not the records_written/error a reader might assume.
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


async def fetch_region_window(
    client: GpmImergClient, region: str, *, end: date, days: int,
) -> RegionWindow:
    """Every available day of one region's grid.

    Fetched NEWEST FIRST, returned oldest first (which is the order
    compute_rainstorm expects). The fetch order is invisible on a healthy run
    and decides everything on a broken one: it fixes which days survive when
    the archive starts refusing us part-way through. Spending the healthy part
    of a run on 90-day-old history and leaving today to whatever is left is
    exactly backwards for a warning feed — baseline depth degrades gracefully,
    a missing today does not.
    """
    lon0, lon1, lat0, lat1 = REGIONS[region]
    grids: list[RegionGrid] = []
    consecutive_failures = 0
    for offset in range(days):
        day = end - timedelta(days=offset)
        try:
            grid = await client.region_grid(
                lon0=lon0, lon1=lon1, lat0=lat0, lat1=lat1, day=day,
            )
        except ImergAuthError:
            raise
        except Exception as exc:            # noqa: BLE001 — one bad day
            # %r, NOT %s. httpx timeout exceptions stringify to the EMPTY
            # STRING — str(ReadTimeout('')) == '' — so this line once logged
            # "imerg region nigeria 2024-09-30 skipped: " sixty-eight times in
            # a row and told an operator nothing at all about why. repr() keeps
            # the class name when there is no message: ReadTimeout('').
            log.warning("imerg region %s %s skipped: %r", region, day, exc)
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error(
                    "imerg region %s: %d consecutive failures ending %s — "
                    "abandoning the window; the coverage guard will refuse it",
                    region, consecutive_failures, day,
                )
                break
            continue
        consecutive_failures = 0
        if grid is not None:
            grids.append(grid)
    grids.sort(key=lambda g: g.day)
    return RegionWindow(
        region=region, grids=grids, requested_days=days, end=end,
    )


async def scan_tenant(
    session: AsyncSession, tenant: str, *,
    window: RegionWindow, trigger: str = "scheduled",
) -> int:
    """Scan every LGA of one tenant against a pre-fetched region window."""
    grids = window.grids
    started_at = datetime.now(timezone.utc)
    await set_tenant_schema(session, tenant)

    batch = select_lgas(tenant, full=True)      # cheap feed → no rolling slice
    if not batch:
        await _record_run(session, tenant=tenant, written=0,
                          started_at=started_at, trigger=trigger)
        return 0

    await _replace_prior(session)
    written = 0
    for g in batch:
        # Sample this LGA out of the already-fetched grids. Days with no
        # granule are simply absent, never zero — a gap is 'unknown', and
        # zero-filling would drag the baseline down and manufacture anomalies.
        series = [
            s for s in (grid.sample(g["lon"], g["lat"]) for grid in grids)
            if s is not None
        ]
        if len(series) <= 1:
            continue
        sig = compute_rainstorm([r.max_mm for r in series])
        if sig is None:
            continue
        await _insert(session, tenant=tenant, lga=g["lga"], lon=g["lon"],
                      lat=g["lat"], sig=sig, observed=series[-1].day)
        written += 1

    await _record_run(session, tenant=tenant, written=written,
                      started_at=started_at, trigger=trigger)
    return written


async def run(
    trigger: str = "scheduled", today: date | None = None,
) -> dict[str, int]:
    """Sweep every pilot tenant. Returns {tenant: advisories_written}.

    Each REGION's grid window is fetched once and shared by every tenant in
    it, so Nigeria's eight tenants cost one set of requests rather than eight.
    """
    client = GpmImergClient()
    if not client.configured:
        log.warning("rainfall scan: no EARTHDATA_TOKEN — skipped")
        return {}

    end = (today or date.today()) - timedelta(days=LATENCY_DAYS)
    windows: dict[str, RegionWindow] = {}
    for region in REGIONS:
        window = await fetch_region_window(
            client, region, end=end, days=BASELINE_DAYS,
        )
        windows[region] = window
        log.info(
            "imerg region %s: %d/%d days (%.0f%%), newest %s",
            region, len(window.grids), window.requested_days,
            100 * window.coverage, window.newest,
        )

    results: dict[str, int] = {}
    factory = get_session_factory()
    async with factory() as session:
        for tenant in sorted(PILOT_TENANT_IDS):
            window = windows.get(TENANT_REGION.get(tenant, ""))
            reason = (
                window.unusable_reason() if window else "no region mapped"
            )
            if reason:
                # Record the run as FAILED rather than writing zero advisories.
                # A quiet zero is indistinguishable from "no exceptional
                # rainfall anywhere", which is the one thing a warning feed
                # must never fake — the same distinction shockguard_scan draws
                # between "not checked" and "no signal".
                #
                # Prior advisories are deliberately left in place: they were
                # legitimately computed, and wiping the map because the archive
                # hiccuped would be its own kind of lie. The feed status is
                # what carries the truth that today's run did not complete.
                log.warning("rainfall scan %s: %s", tenant, reason)
                await _record_run(
                    session, tenant=tenant, written=0,
                    started_at=datetime.now(timezone.utc),
                    trigger=trigger, error=reason,
                )
                results[tenant] = 0
                continue
            try:
                results[tenant] = await scan_tenant(
                    session, tenant, window=window, trigger=trigger,
                )
            except ImergAuthError as exc:
                # Credentials are global, not per-tenant: continuing would emit
                # the same 401 for every remaining LGA and leave every tenant
                # looking storm-free. Stop and surface it.
                log.error("rainstorm scan aborted — %s", exc)
                await session.rollback()
                raise
            except Exception as exc:            # noqa: BLE001 — one bad tenant
                log.exception("rainfall scan failed for %s: %r", tenant, exc)
                await session.rollback()
                results[tenant] = 0
        await session.commit()
    total = sum(results.values())
    log.info("rainfall scan: %d advisories across %d tenants", total, len(results))
    return results


async def run_rainfall_scan() -> None:
    """Scheduler entry point."""
    await run(trigger="scheduled")
