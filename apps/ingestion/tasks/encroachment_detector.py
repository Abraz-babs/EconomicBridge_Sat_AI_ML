"""Encroachment & land-disturbance detector — Farmland Protection.

Fuses three LIVE satellite signals per tenant ROI into a year-round farmland
risk indicator, independent of fire season:

  * Sentinel-2 NDVI deviation  -> vegetation change (grazing / clearing)
  * Sentinel-1 SAR change       -> land-surface disturbance (tracks, trampling)
  * NASA FIRMS fire count       -> burning / hostile activity

When the fused score clears the watch threshold, one alert_events row is written
(alert_type='conflict', model_name='encroachment_detector_v1',
human_review_required=True). These are MODEL-DERIVED RISK INDICATORS from
ROI-aggregate satellite anomalies, NOT confirmed incidents -- honest provenance.
Higher-resolution / per-LGA data (e.g. NASRDA NCRS) would sharpen them from
ROI-level to field-level. Runs for every pilot tenant.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from statistics import mean, pstdev
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from sources.nasa_firms import PILOT_BBOX

# Per-LGA centroids (built by scripts/build_lga_centroids.py) — used to label
# each ROI-level alert with a representative LGA name + real coordinates.
_LGA_CENTROIDS_PATH = Path(__file__).resolve().parents[1] / "data" / "lga_centroids.json"

log = logging.getLogger(__name__)

MODEL_VERSION = "encroachment_detector_v1"
RUN_SOURCE = "encroachment_detector_v1"

RECENT_N = 3          # most-recent acquisitions treated as "recent" vs baseline
MIN_POINTS = 6        # need this many obs in a series to judge
NDVI_SCALE = 2.0      # z-score magnitude -> 0..1 saturation
SAR_SCALE = 2.0
FIRE_SATURATION = 8   # this many recent fires -> full fire component
ALERT_THRESHOLD = 0.42  # fused score at/above this raises a watch alert

# Impact ESTIMATES shown on the alert card (model-derived, human_review_required
# — NOT measured). Anchored to smallholder reality and the seed alerts' own
# ratios (~4.6 livelihoods/ha, ~₦200k gross crop value/ha/season). Severity sets
# the base disturbed extent + the conflict-risk window the module advertises
# (24-72h); the score modulates the extent within the band.
SEVERITY_IMPACT_HA_HOURS = {
    "critical": (160, 24),
    "high":     (90, 48),
    "medium":   (45, 72),
    "low":      (20, 96),
}
LIVELIHOODS_PER_HA = 4.6
CROP_VALUE_NGN_PER_HA = 200_000


@dataclass
class EncroachmentSignal:
    """Result of fusing the three satellite signals for one tenant ROI."""

    score: float
    severity: str
    ndvi_z: float        # signed: negative = vegetation loss
    sar_z: float         # absolute land-surface change magnitude
    fire_count: int
    components: dict
    latest_obs: date | None


def _tanh01(z: float, scale: float) -> float:
    """Map a magnitude (>=0) to 0..1 with soft saturation."""
    return math.tanh(max(0.0, z) / scale)


@lru_cache(maxsize=1)
def _lga_index() -> dict:
    try:
        return json.loads(_LGA_CENTROIDS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — labelling is best-effort
        return {}


def representative_lga(tenant: str) -> tuple[str | None, float, float]:
    """An LGA name + coordinates representing the tenant ROI for display.

    Picks the LGA whose centroid is closest to the ROI centre, so the alert
    shows a real place instead of bare coordinates. The alert remains an
    ROI-level (whole-territory) indicator — the LGA is representative, not a
    pinpointed location.
    """
    bbox = PILOT_BBOX[tenant]
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    lgas = _lga_index().get(tenant, [])
    if not lgas:
        return None, cx, cy
    nearest = min(lgas, key=lambda g: (g["lon"] - cx) ** 2 + (g["lat"] - cy) ** 2)
    return nearest["lga"], nearest["lon"], nearest["lat"]


def _severity(score: float) -> str:
    # Single-signal scores cap at ~0.6 (the corroboration floor), so they land
    # in "medium" (a watch). high/critical require corroborating signals and
    # are reached only in the dry/conflict season — see compute_encroachment.
    if score >= 0.80:
        return "critical"
    if score >= 0.62:
        return "high"
    if score >= 0.42:
        return "medium"
    return "low"


def compute_encroachment(
    ndvi_vals: list[float],
    sar_vals: list[float],
    fire_count: int,
    latest_obs: date | None = None,
) -> EncroachmentSignal | None:
    """Pure fusion of the three signals. Returns None if data is too thin.

    Args:
        ndvi_vals: Sentinel-2 NDVI means, oldest-to-newest.
        sar_vals: Sentinel-1 SAR backscatter (dB), oldest-to-newest.
        fire_count: recent FIRMS detections over the ROI.
        latest_obs: date of the most recent observation (for dedup).
    """
    if len(ndvi_vals) < MIN_POINTS or len(sar_vals) < MIN_POINTS:
        return None

    def split(vals: list[float]) -> tuple[list[float], list[float]]:
        return vals[:-RECENT_N], vals[-RECENT_N:]

    nb, nr = split(ndvi_vals)
    sb, sr = split(sar_vals)
    n_std = pstdev(nb) or 1e-6
    s_std = pstdev(sb) or 1e-6
    ndvi_z = (mean(nr) - mean(nb)) / n_std      # signed
    sar_z = abs(mean(sr) - mean(sb)) / s_std    # magnitude

    # Encroachment is vegetation LOSS — only a NDVI DROP counts. Vegetation
    # gain (wet-season greening) is NOT a disturbance signal and is ignored,
    # so we never flag healthy crops as risk.
    c_ndvi = _tanh01(max(0.0, -ndvi_z), NDVI_SCALE)
    c_sar = _tanh01(sar_z, SAR_SCALE)               # radar land-surface change
    c_fire = min(1.0, fire_count / FIRE_SATURATION)

    # Corroboration-weighted confidence. A LONE signal is ambiguous — a single
    # SAR change in the wet season is often just soil moisture, not
    # encroachment — so on its own it only earns a moderate watch (×0.6).
    # Corroborating signals (vegetation loss, fire) raise confidence toward the
    # full magnitude, and genuine multi-signal events reach high/critical.
    comps = (c_ndvi, c_sar, c_fire)
    primary = max(comps)
    corroboration = min(1.0, sum(comps) - primary)
    score = min(1.0, primary * (0.6 + 0.4 * corroboration))
    return EncroachmentSignal(
        score=round(score, 4),
        severity=_severity(score),
        ndvi_z=round(ndvi_z, 3),
        sar_z=round(sar_z, 3),
        fire_count=fire_count,
        components={
            "ndvi_loss": round(c_ndvi, 3), "sar_change": round(c_sar, 3),
            "fire": round(c_fire, 3), "fusion": "max + 0.25*corroboration",
        },
        latest_obs=latest_obs,
    )


# ─── Database access ───────────────────────────────────────────────────────


async def _load_series(session: AsyncSession):
    rows = (await session.execute(text(
        "SELECT observed_at, ndvi_mean, sar_backscatter_db "
        "FROM satellite_observations WHERE source = 'sentinel_stat_v1' "
        "ORDER BY observed_at"
    ))).all()
    ndvi = [r.ndvi_mean for r in rows if r.ndvi_mean is not None]
    sar = [r.sar_backscatter_db for r in rows if r.sar_backscatter_db is not None]
    latest = rows[-1].observed_at if rows else None
    return ndvi, sar, latest


async def _recent_fire_count(session: AsyncSession) -> int:
    try:
        r = (await session.execute(text(
            "SELECT count(*) FROM heat_signatures "
            "WHERE created_at > now() - interval '30 days'"
        ))).scalar()
        return int(r or 0)
    except Exception:  # noqa: BLE001 — fire signal is optional
        return 0


def _input_hash(tenant: str, latest_obs: date | None) -> str:
    return hashlib.sha256(json.dumps(
        {"t": tenant, "obs": str(latest_obs), "m": MODEL_VERSION},
        sort_keys=True,
    ).encode("utf-8")).hexdigest()


def _impact_estimate(severity: str, score: float) -> tuple[int, int, int, int]:
    """Model-derived (area_ha, livelihoods, economic_value_ngn, breach_hours)
    for the alert card. ESTIMATES, not measurements — the alert stays
    human_review_required. Extent scales within the severity band by score.
    """
    base_ha, breach_h = SEVERITY_IMPACT_HA_HOURS.get(severity, (20, 96))
    area_ha = max(1, round(base_ha * (0.7 + 0.6 * min(1.0, score))))
    livelihoods = round(area_ha * LIVELIHOODS_PER_HA)
    econ_ngn = round(area_ha * CROP_VALUE_NGN_PER_HA)
    return area_ha, livelihoods, econ_ngn, breach_h


async def _insert_alert(
    session: AsyncSession, *, tenant: str, signal: EncroachmentSignal,
    input_hash: str, trace_id: UUID,
) -> None:
    lga_name, lon, lat = representative_lga(tenant)
    parts = []
    if signal.ndvi_z <= -0.5:
        parts.append(f"vegetation loss {signal.ndvi_z:.1f}σ")
    if signal.sar_z >= 1.0:
        parts.append(f"radar land-surface change {signal.sar_z:.1f}σ")
    if signal.fire_count:
        parts.append(f"{signal.fire_count} fire(s)")
    trigger = ", ".join(parts) if parts else "low-level land anomaly"
    where = f" near {lga_name}" if lga_name else ""
    zone = f"Land-surface change risk (ROI-level){where}: {trigger}"
    area_ha, livelihoods, econ_ngn, breach_h = _impact_estimate(
        signal.severity, signal.score)
    await session.execute(text("""
        INSERT INTO alert_events (
            id, tenant_id, alert_type, severity, status, zone_name, lga,
            location, confidence_score,
            affected_area_ha, livelihoods_at_risk, economic_value_ngn,
            predicted_breach_hours, satellite_source, satellite_pass_time,
            model_name, model_version, model_input_hash, shap_values,
            human_review_required, created_at, updated_at, created_by
        ) VALUES (
            :id, :tenant_id, 'conflict', :severity, 'pending_review', :zone, :lga,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :confidence,
            :area_ha, :livelihoods, :econ_ngn,
            :breach_h,
            'Sentinel-2 NDVI + Sentinel-1 SAR + NASA FIRMS (fused land-disturbance risk)',
            NOW(),
            :model_name, :model_version, :hash, CAST(:shap AS JSONB),
            TRUE, NOW(), NOW(), :trace_id
        )
    """), {
        "id": uuid4(), "tenant_id": tenant, "severity": signal.severity,
        "zone": zone, "lga": lga_name, "lon": lon, "lat": lat,
        "confidence": signal.score,
        "area_ha": area_ha, "livelihoods": livelihoods, "econ_ngn": econ_ngn,
        "breach_h": breach_h,
        "model_name": MODEL_VERSION, "model_version": MODEL_VERSION,
        "hash": input_hash, "shap": json.dumps(signal.components),
        "trace_id": trace_id,
    })


async def detect_for_tenant(session: AsyncSession, tenant: str) -> str:
    """Evaluate one tenant; refresh its current watch from the latest scan.

    The encroachment watch is a continuously-refreshed ROI signal, so each run
    clears the prior un-actioned (pending_review) auto-watch and writes the
    current one. Officer-actioned rows (acknowledged/resolved) are preserved.
    """
    await set_tenant_schema(session, tenant)
    ndvi, sar, latest = await _load_series(session)
    fires = await _recent_fire_count(session)
    signal = compute_encroachment(ndvi, sar, fires, latest)
    await session.execute(text(
        "DELETE FROM alert_events "
        "WHERE model_name = :m AND status = 'pending_review'"
    ), {"m": MODEL_VERSION})
    if signal is None:
        return "skipped: insufficient observations"
    if signal.score < ALERT_THRESHOLD:
        return f"no alert (score {signal.score})"
    h = _input_hash(tenant, latest)
    await _insert_alert(session, tenant=tenant, signal=signal,
                        input_hash=h, trace_id=uuid4())
    return f"ALERT {signal.severity} (score {signal.score})"


async def run_encroachment_sweep(tenants: list[str] | None = None) -> dict[str, str]:
    """Run the detector across every pilot tenant. Failures are isolated."""
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
                log.exception("encroachment failed tenant=%s", t)
    log.info("encroachment sweep: %s", out)
    return out
