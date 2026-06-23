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
from statistics import mean, pstdev

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from tasks.encroachment_detector import representative_lga

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


async def _insert_event(session: AsyncSession, *, tenant: str, sig: ShockSignal) -> None:
    lga_name, lon, lat = representative_lga(tenant)
    verb = "flooding" if sig.event_type == "flood" else "vegetation drought"
    where = f" near {lga_name}" if lga_name else ""
    zone = (f"{verb.capitalize()} signature (ROI-level){where}: "
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


async def detect_for_tenant(session: AsyncSession, tenant: str) -> str:
    """Re-scan one tenant; replace its prior scan events with current ones."""
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
    if not written:
        return "clear (no flood/drought signal)"
    return ", ".join(f"{s.event_type} {s.severity} ({s.confidence})" for s in written)


async def run_shockguard_scan(tenants: list[str] | None = None) -> dict[str, str]:
    """Re-scan every pilot tenant. Failures isolated; one session per tenant."""
    target = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    out: dict[str, str] = {}
    for t in target:
        async with factory() as session:
            try:
                out[t] = await detect_for_tenant(session, t)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 — isolate per tenant
                out[t] = f"failed: {exc!s}"
                log.exception("shockguard scan failed tenant=%s", t)
    log.info("shockguard scan: %s", out)
    return out
