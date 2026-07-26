"""Scheduled per-LGA exceptional-rainfall scan (flood-risk advisory).

NOT WIRED INTO THE SCHEDULER, deliberately — see the two blockers at the end.

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
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from processors.rainstorm_signal import RainstormSignal, compute_rainstorm
from sources.gpm_imerg import GpmImergClient, ImergAuthError
from tasks.encroachment_detector import select_lgas

log = logging.getLogger(__name__)

SOURCE = "rainstorm_scan_v1"
DETECTOR = "imerg_extreme_rainfall"
DETECTOR_VERSION = "1.0.0"

# Days of history per LGA. A p99 wet-day percentile needs MIN_WET_DAYS (20)
# wet days behind it; at roughly half of rainy-season days being wet, 90 days
# is the smallest window that reliably clears that bar.
#
# BLOCKER 1 — fetch strategy. At 90 days x 447 LGAs this is ~40,000 OPeNDAP
# calls per run at ~3 s each. Before scheduling, either (a) fetch a per-TENANT
# bbox instead of a per-LGA point (one call covers all of a state's LGAs, so a
# full baseline rebuild is ~900 calls and the daily delta is ~10), or (b) cache
# each LGA's p99 threshold and fetch only the current day. (a) is the cleaner
# fix and the client already supports arbitrary index windows.
#
# BLOCKER 2 — no operational validation. The detector is calibrated against
# real climatology but has never fired on a known event, because the four we
# have are not rainfall-visible. It needs a season of shadow running before
# anyone is alerted from it.
BASELINE_DAYS = 90
# IMERG Late publishes ~1 day behind; asking for today returns nothing.
LATENCY_DAYS = 1


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


async def scan_tenant(
    session: AsyncSession, client: GpmImergClient, tenant: str, *,
    trigger: str = "scheduled", today: date | None = None,
) -> int:
    """Scan every LGA of one tenant. Returns rows written."""
    started_at = datetime.now(timezone.utc)
    await set_tenant_schema(session, tenant)
    end = (today or date.today()) - timedelta(days=LATENCY_DAYS)

    batch = select_lgas(tenant, full=True)      # cheap feed → no rolling slice
    if not batch:
        await _record_run(session, tenant=tenant, written=0,
                          started_at=started_at, trigger=trigger)
        return 0

    await _replace_prior(session)
    written = 0
    for g in batch:
        series = await client.series(
            g["lon"], g["lat"], end=end, days=BASELINE_DAYS,
        )
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


async def run(trigger: str = "scheduled") -> dict[str, int]:
    """Sweep every pilot tenant. Returns {tenant: rows_written}."""
    client = GpmImergClient()
    if not client.configured:
        log.warning("rainstorm scan: no EARTHDATA_TOKEN — skipped")
        return {}

    results: dict[str, int] = {}
    factory = get_session_factory()
    async with factory() as session:
        for tenant in sorted(PILOT_TENANT_IDS):
            try:
                results[tenant] = await scan_tenant(
                    session, client, tenant, trigger=trigger,
                )
            except ImergAuthError as exc:
                # Credentials are global, not per-tenant: continuing would emit
                # the same 401 for every remaining LGA and leave every tenant
                # looking storm-free. Stop and surface it.
                log.error("rainstorm scan aborted — %s", exc)
                await session.rollback()
                raise
            except Exception as exc:            # noqa: BLE001 — one bad tenant
                log.exception("rainstorm scan failed for %s: %s", tenant, exc)
                await session.rollback()
                results[tenant] = 0
        await session.commit()
    total = sum(results.values())
    log.info("rainstorm scan: %d events across %d tenants", total, len(results))
    return results
