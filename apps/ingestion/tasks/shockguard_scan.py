"""Scheduled ShockGuard flood + drought detector.

Turns the live Sentinel observations into shock_events on a schedule, so the
ShockGuard feed refreshes itself as new satellite passes arrive (previously
events were created only on-demand and went stale).

  * Flood   = a sharp DROP in Sentinel-1 SAR backscatter — open water reflects
    radar away from the sensor, so a flooded ROI returns much less signal.
  * Drought = a sharp DROP in Sentinel-2 NDVI below the recent baseline.

ROI-level, model-derived risk indicators (requires_human_review=True), honestly
tagged source='shockguard_scan_v1'. Runs for every pilot tenant, daily; each run
replaces the prior scan's events so the feed stays current.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from sources.copernicus import CopernicusClient, CopernicusError
from sources.sentinel_statistical import SentinelStatisticalClient
from tasks.encroachment_detector import (
    _fetch_lga_series,
    representative_lga,
    select_lgas,
)

log = logging.getLogger(__name__)

SOURCE = "shockguard_scan_v1"
DETECTOR = "shockguard_satellite_anomaly"
DETECTOR_VERSION = "v1"

RECENT_N = 3
MIN_POINTS = 6
SAR_SCALE = 2.5       # SAR backscatter z-magnitude -> 0..1 saturation
NDVI_SCALE = 2.0
THRESHOLD = 0.55      # confidence at/above this raises an event (serious feed)


@dataclass
class ShockSignal:
    event_type: str       # 'flood' | 'drought'
    z: float              # signed; negative = the drop we flag
    confidence: float
    severity: str
    band: str


def _severity(c: float) -> str:
    if c >= 0.82:
        return "critical"
    if c >= 0.68:
        return "high"
    return "medium"


def _band(c: float) -> str:
    if c >= 0.75:
        return "HIGH"
    if c >= 0.55:
        return "MEDIUM"
    return "LOW"


def compute_shock(vals: list[float], event_type: str, scale: float) -> ShockSignal | None:
    """Flag a flood/drought from a DROP in the series. Returns None if quiet.

    Args:
        vals: the satellite series oldest-to-newest (SAR dB for flood, NDVI for
            drought).
        event_type: 'flood' or 'drought'.
        scale: z-magnitude saturation scale for the confidence curve.
    """
    if len(vals) < MIN_POINTS:
        return None
    base, recent = vals[:-RECENT_N], vals[-RECENT_N:]
    std = pstdev(base) or 1e-6
    z = (mean(recent) - mean(base)) / std        # negative = drop
    drop = max(0.0, -z)
    c = math.tanh(drop / scale)
    if c < THRESHOLD:
        return None
    return ShockSignal(event_type, round(z, 3), round(c, 4), _severity(c), _band(c))


# ─── Database access ───────────────────────────────────────────────────────


async def _load_series(session: AsyncSession):
    rows = (await session.execute(text(
        "SELECT ndvi_mean, sar_backscatter_db FROM satellite_observations "
        "WHERE source = 'sentinel_stat_v1' ORDER BY observed_at"
    ))).all()
    ndvi = [r.ndvi_mean for r in rows if r.ndvi_mean is not None]
    sar = [r.sar_backscatter_db for r in rows if r.sar_backscatter_db is not None]
    return ndvi, sar


async def _insert_event(
    session: AsyncSession, *, tenant: str, sig: ShockSignal,
    lga_name: str | None = None, lon: float | None = None,
    lat: float | None = None, scope_label: str = "ROI-level",
) -> None:
    # Per-LGA callers pass the LGA + centroid; the ROI fallback derives one.
    if lga_name is None or lon is None or lat is None:
        lga_name, lon, lat = representative_lga(tenant)
    verb = "flooding" if sig.event_type == "flood" else "vegetation drought"
    where = f" near {lga_name}" if lga_name else ""
    zone = (f"{verb.capitalize()} signature ({scope_label}){where}: "
            f"{'SAR' if sig.event_type == 'flood' else 'NDVI'} drop {sig.z:.1f}σ")
    metrics = {"z": sig.z, "confidence": sig.confidence,
               "signal": "Sentinel-1 SAR" if sig.event_type == "flood" else "Sentinel-2 NDVI"}
    await session.execute(text("""
        INSERT INTO shock_events (
            tenant_id, event_type, detector_name, detector_version,
            severity, confidence, confidence_band, requires_human_review,
            projected_onset_hours, affected_area_km2, population_at_risk,
            location, lga, zone_name, metrics, source
        ) VALUES (
            :tenant_id, :etype, :detector, :dver,
            :severity, :confidence, :band, TRUE,
            NULL, NULL, NULL,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            :lga, :zone, CAST(:metrics AS JSONB), :source
        )
    """), {
        "tenant_id": tenant, "etype": sig.event_type, "detector": DETECTOR,
        "dver": DETECTOR_VERSION, "severity": sig.severity,
        "confidence": sig.confidence, "band": sig.band, "lon": lon, "lat": lat,
        "lga": lga_name, "zone": zone, "metrics": json.dumps(metrics),
        "source": SOURCE,
    })


async def _record_run(
    session: AsyncSession, *, tenant: str, written: int,
    started_at: datetime, trigger: str,
) -> None:
    """Stamp public.ingestion_runs so the dashboard can show 'last scan' and
    prove the detector is live even when no shock is active."""
    await session.execute(text("""
        INSERT INTO public.ingestion_runs (
            id, source, tenant_id, trigger, started_at, finished_at,
            status, records_ingested, dry_run
        ) VALUES (
            :id, :source, :tenant, :trigger, :started_at, NOW(),
            'succeeded', :written, FALSE
        )
    """), {
        "id": uuid4(), "source": SOURCE, "tenant": tenant, "trigger": trigger,
        "started_at": started_at, "written": written,
    })


async def detect_for_tenant(session: AsyncSession, tenant: str) -> int:
    """Re-scan one tenant; replace its prior scan events with current ones.

    Returns the number of shock events written (0 = scanned, all clear).
    """
    await set_tenant_schema(session, tenant)
    ndvi, sar = await _load_series(session)
    # Idempotent: clear the previous scan's events before writing fresh ones.
    await session.execute(
        text("DELETE FROM shock_events WHERE source = :s"), {"s": SOURCE})
    flood = compute_shock(sar, "flood", SAR_SCALE)
    drought = compute_shock(ndvi, "drought", NDVI_SCALE)
    written = [s for s in (flood, drought) if s is not None]
    for sig in written:
        await _insert_event(session, tenant=tenant, sig=sig)
    return len(written)


async def detect_per_lga_for_tenant(
    session: AsyncSession, client: SentinelStatisticalClient, tenant: str,
    *, full: bool = False, day: int | None = None,
) -> int:
    """Per-LGA flood/drought scan: each LGA from its OWN Sentinel-1 SAR +
    Sentinel-2 NDVI series, rolling on the ~6-day revisit cadence. Only the
    scanned LGAs' events are refreshed (a 429/error keeps that LGA's prior
    events), so the statewide picture stays populated between revisits.

    Returns the number of shock events written across the scanned LGAs.
    """
    await set_tenant_schema(session, tenant)
    batch = select_lgas(tenant, full=full, day=day)
    if not batch:
        return await detect_for_tenant(session, tenant)  # ROI fallback

    events = 0
    for g in batch:
        # Fetch FIRST — only refresh this LGA on a successful read, so a rate
        # limit / error skips it without wiping its prior shock events.
        try:
            ndvi, sar, _latest = await _fetch_lga_series(client, g["lon"], g["lat"])
        except CopernicusError as exc:
            log.warning("shockguard per-LGA CDSE error tenant=%s lga=%s: %s",
                        tenant, g.get("lga"), exc)
            continue
        flood = compute_shock(sar, "flood", SAR_SCALE)
        drought = compute_shock(ndvi, "drought", NDVI_SCALE)
        await session.execute(text(
            "DELETE FROM shock_events WHERE source = :s AND lga = :lga"
        ), {"s": SOURCE, "lga": g["lga"]})
        for sig in (s for s in (flood, drought) if s is not None):
            await _insert_event(
                session, tenant=tenant, sig=sig,
                lga_name=g["lga"], lon=g["lon"], lat=g["lat"],
                scope_label="LGA-level",
            )
            events += 1
    return events


async def run_shockguard_scan(
    tenants: list[str] | None = None, *, trigger: str = "scheduled",
    full: bool = False,
) -> dict[str, str]:
    """Re-scan every pilot tenant. Failures isolated; one session per tenant.

    Per-LGA flood/drought when CDSE creds are configured (statewide coverage,
    revisit-matched rolling); ROI-level fallback otherwise. `full=True` scans
    every LGA at once (initial seed / on-demand). Every successful tenant scan
    stamps public.ingestion_runs so the panel can show a 'last scan' time.
    """
    target = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    client = SentinelStatisticalClient(CopernicusClient())
    per_lga = client.configured
    out: dict[str, str] = {}
    for t in target:
        async with factory() as session:
            started = datetime.now(timezone.utc)
            try:
                if per_lga:
                    count = await detect_per_lga_for_tenant(
                        session, client, t, full=full)
                else:
                    count = await detect_for_tenant(session, t)
                await _record_run(
                    session, tenant=t, written=count,
                    started_at=started, trigger=trigger,
                )
                await session.commit()
                out[t] = "clear (no flood/drought signal)" if count == 0 \
                    else f"{count} shock event(s)"
            except Exception as exc:  # noqa: BLE001 — isolate per tenant
                out[t] = f"failed: {exc!s}"
                log.exception("shockguard scan failed tenant=%s", t)
    log.info("shockguard scan (mode=%s): %s",
             "per-LGA" if per_lga else "ROI", out)
    return out
