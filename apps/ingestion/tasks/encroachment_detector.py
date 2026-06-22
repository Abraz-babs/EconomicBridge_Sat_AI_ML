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
from statistics import mean, pstdev
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from sources.nasa_firms import PILOT_BBOX

log = logging.getLogger(__name__)

MODEL_VERSION = "encroachment_detector_v1"
RUN_SOURCE = "encroachment_detector_v1"

# Fusion weights (sum to 1.0). SAR is the most reliable all-weather
# disturbance signal, so it carries the most weight.
W_NDVI = 0.40
W_SAR = 0.45
W_FIRE = 0.15

RECENT_N = 3          # most-recent acquisitions treated as "recent" vs baseline
MIN_POINTS = 6        # need this many obs in a series to judge
NDVI_SCALE = 2.0      # z-score magnitude -> 0..1 saturation
SAR_SCALE = 2.0
FIRE_SATURATION = 8   # this many recent fires -> full fire component
ALERT_THRESHOLD = 0.45  # fused score at/above this raises a watch alert


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


def _severity(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.70:
        return "high"
    if score >= 0.55:
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

    # A vegetation DROP (loss) is the stronger encroachment signal; any large
    # deviation is land change, so give a gain partial credit.
    ndvi_mag = (-ndvi_z) if ndvi_z < 0 else (0.5 * ndvi_z)
    c_ndvi = _tanh01(ndvi_mag, NDVI_SCALE)
    c_sar = _tanh01(sar_z, SAR_SCALE)
    c_fire = min(1.0, fire_count / FIRE_SATURATION)

    score = min(1.0, W_NDVI * c_ndvi + W_SAR * c_sar + W_FIRE * c_fire)
    return EncroachmentSignal(
        score=round(score, 4),
        severity=_severity(score),
        ndvi_z=round(ndvi_z, 3),
        sar_z=round(sar_z, 3),
        fire_count=fire_count,
        components={
            "ndvi": round(c_ndvi, 3), "sar": round(c_sar, 3),
            "fire": round(c_fire, 3),
            "weights": {"ndvi": W_NDVI, "sar": W_SAR, "fire": W_FIRE},
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


async def _alert_exists(session: AsyncSession, input_hash: str) -> bool:
    r = (await session.execute(
        text("SELECT 1 FROM alert_events WHERE model_input_hash = :h LIMIT 1"),
        {"h": input_hash},
    )).first()
    return r is not None


async def _insert_alert(
    session: AsyncSession, *, tenant: str, signal: EncroachmentSignal,
    input_hash: str, trace_id: UUID,
) -> None:
    bbox = PILOT_BBOX[tenant]
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    drift = "vegetation loss" if signal.ndvi_z < 0 else "vegetation change"
    zone = (f"ROI land-surface change: {drift} {signal.ndvi_z:+.1f}σ, "
            f"SAR Δ{signal.sar_z:.1f}σ"
            + (f", {signal.fire_count} fire(s)" if signal.fire_count else ""))
    await session.execute(text("""
        INSERT INTO alert_events (
            id, tenant_id, alert_type, severity, status, zone_name, lga,
            location, confidence_score,
            affected_area_ha, livelihoods_at_risk, economic_value_ngn,
            predicted_breach_hours, satellite_source, satellite_pass_time,
            model_name, model_version, model_input_hash, shap_values,
            human_review_required, created_at, updated_at, created_by
        ) VALUES (
            :id, :tenant_id, 'conflict', :severity, 'pending_review', :zone, NULL,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :confidence,
            NULL, NULL, NULL,
            NULL,
            'Sentinel-2 NDVI + Sentinel-1 SAR + NASA FIRMS (fused land-disturbance risk)',
            NOW(),
            :model_name, :model_version, :hash, CAST(:shap AS JSONB),
            TRUE, NOW(), NOW(), :trace_id
        )
    """), {
        "id": uuid4(), "tenant_id": tenant, "severity": signal.severity,
        "zone": zone, "lon": lon, "lat": lat, "confidence": signal.score,
        "model_name": MODEL_VERSION, "model_version": MODEL_VERSION,
        "hash": input_hash, "shap": json.dumps(signal.components),
        "trace_id": trace_id,
    })


async def detect_for_tenant(session: AsyncSession, tenant: str) -> str:
    """Evaluate one tenant; insert an alert if the fused score clears the bar."""
    await set_tenant_schema(session, tenant)
    ndvi, sar, latest = await _load_series(session)
    fires = await _recent_fire_count(session)
    signal = compute_encroachment(ndvi, sar, fires, latest)
    if signal is None:
        return "skipped: insufficient observations"
    if signal.score < ALERT_THRESHOLD:
        return f"no alert (score {signal.score})"
    h = _input_hash(tenant, latest)
    if await _alert_exists(session, h):
        return f"exists (score {signal.score})"
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
