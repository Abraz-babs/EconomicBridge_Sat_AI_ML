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
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import mean, pstdev
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db import PILOT_TENANT_IDS, get_session_factory, set_tenant_schema
from sources.copernicus import CopernicusClient, CopernicusError
from sources.farm_check import FARM_RESOLUTION_DEG, bbox_around
from sources.nasa_firms import PILOT_BBOX
from sources.sentinel_statistical import (
    EVALSCRIPT_S1_VV_DB,
    EVALSCRIPT_S2_NDVI_CLOUDMASKED,
    SentinelStatisticalClient,
)
from sources.viirs_raster import sample_radiance

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
# Fused score at/above this raises a watch alert. Env-tunable so the watch
# sensitivity can be dialled from the task definition without a code change.
# 0.30 surfaces genuine low-level land-surface deviations (≈1.1σ+ SAR change) as
# honestly-labelled "low" watches across the state; _severity still grades
# medium (≥0.42) / high (≥0.62) / critical (≥0.80) above that. Truly calm LGAs
# (no NDVI loss, negligible SAR change) score below this and stay un-flagged.
ALERT_THRESHOLD = float(os.environ.get("ENCROACHMENT_ALERT_THRESHOLD", "0.30"))

# ─── Per-LGA sweep (statewide coverage instead of one ROI-averaged point).
#     Each LGA gets its OWN Sentinel-2 NDVI + Sentinel-1 SAR series from CDSE
#     (small box around the centroid), so local land disturbance surfaces where
#     it happens — ROI-averaging washes it out.
#
#     COVERAGE = every LGA in every state, refreshed on a REVISIT_DAYS rolling
#     cadence: each daily run scans ~1/REVISIT_DAYS of the LGAs (the ones "due"),
#     so all are covered over one Sentinel revisit (~6 days) while daily CDSE
#     cost stays bounded (~150 requests/day ≈ ~4.5k PU/month for ~450 LGAs).
#     A `full=True` sweep scans every LGA at once (initial seed / on-demand,
#     ~900 requests). Rolling refresh is per-LGA (we re-evaluate only the due
#     LGAs and keep the others' current watch), so the map stays fully populated.
LGA_BOX_HALF_M = 1500   # ~3 km box around an LGA centroid — captures local farmland
LGA_NDVI_WINDOW_DAYS = 90
LGA_SAR_WINDOW_DAYS = 120
# Sentinel revisit ~5-6 days; refresh each LGA on that cadence (env-tunable).
REVISIT_DAYS = max(1, int(os.environ.get("ENCROACHMENT_REVISIT_DAYS", "6")))

# VIIRS Black Marble "new light in dark farmland" — a YEAR-ROUND human-activity
# signal (NASA, daily). A light appearing where it was dark (baseline below
# NIGHTLIGHT_DARK) flags new settlement / camp / mining activity even when NDVI
# and SAR are quiet (wet-season greening, no fire). Already-lit places score 0 —
# only genuinely NEW light counts. Compared current vs ~6 weeks earlier.
NIGHTLIGHT_DARK = 1.0          # nW/cm²/sr — at/above this an LGA is already "lit"
NIGHTLIGHT_SCALE = 3.0        # radiance increase -> 0..1 saturation
VIIRS_LATENCY_DAYS = 10       # Black Marble publishes ~1 week behind real time
VIIRS_BASELINE_LAG_DAYS = 45  # baseline = ~6 weeks before the current granule

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
    """Result of fusing the satellite signals for one location."""

    score: float
    severity: str
    ndvi_z: float        # signed: negative = vegetation loss
    sar_z: float         # absolute land-surface change magnitude
    fire_count: int
    components: dict
    latest_obs: date | None
    nightlight: float = 0.0   # 0..1 new-light-in-dark-area component


def _tanh01(z: float, scale: float) -> float:
    """Map a magnitude (>=0) to 0..1 with soft saturation."""
    return math.tanh(max(0.0, z) / scale)


def nightlight_newlight(current: float | None, baseline: float | None) -> float:
    """0..1 'new light in a dark area' signal — a meaningful radiance increase
    where it was previously dark. Already-lit places (existing towns) return 0;
    only genuinely NEW light counts as fresh human activity. Year-round (VIIRS
    is daily), so it works when NDVI/SAR are quiet."""
    if current is None or baseline is None:
        return 0.0
    if baseline >= NIGHTLIGHT_DARK:
        return 0.0
    return _tanh01(current - baseline, NIGHTLIGHT_SCALE)


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
    nightlight: float = 0.0,
) -> EncroachmentSignal | None:
    """Pure fusion of the satellite signals. Returns None if data is too thin.

    Args:
        ndvi_vals: Sentinel-2 NDVI means, oldest-to-newest.
        sar_vals: Sentinel-1 SAR backscatter (dB), oldest-to-newest.
        fire_count: recent FIRMS detections over the ROI.
        latest_obs: date of the most recent observation (for dedup).
        nightlight: 0..1 VIIRS new-light-in-dark-area component (year-round).
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
    c_nightlight = max(0.0, min(1.0, nightlight))   # new light in a dark area

    # Corroboration-weighted confidence. A LONE signal is ambiguous — a single
    # SAR change in the wet season is often just soil moisture, not
    # encroachment — so on its own it only earns a moderate watch (×0.6).
    # Corroborating signals (vegetation loss, fire, a new night-light) raise
    # confidence toward the full magnitude; genuine multi-signal events reach
    # high/critical. The new-light component keeps the detector alive year-round.
    comps = (c_ndvi, c_sar, c_fire, c_nightlight)
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
            "fire": round(c_fire, 3), "new_nightlight": round(c_nightlight, 3),
            "fusion": "max + 0.4*corroboration",
        },
        latest_obs=latest_obs,
        nightlight=round(c_nightlight, 3),
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
    lga_name: str | None = None, lon: float | None = None,
    lat: float | None = None, scope_label: str = "ROI-level",
) -> None:
    # Per-LGA callers pass the LGA + its centroid; the ROI fallback derives a
    # representative LGA from the tenant bbox centre.
    if lga_name is None or lon is None or lat is None:
        lga_name, lon, lat = representative_lga(tenant)
    parts = []
    if signal.ndvi_z <= -0.5:
        parts.append(f"vegetation loss {signal.ndvi_z:.1f}σ")
    if signal.sar_z >= 1.0:
        parts.append(f"radar land-surface change {signal.sar_z:.1f}σ")
    if signal.fire_count:
        parts.append(f"{signal.fire_count} fire(s)")
    if signal.nightlight >= 0.3:
        parts.append("new night-light activity")
    trigger = ", ".join(parts) if parts else "low-level land anomaly"
    where = f" near {lga_name}" if lga_name else ""
    zone = f"Land-surface change risk ({scope_label}){where}: {trigger}"
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


# ─── Per-LGA sweep (statewide coverage) ────────────────────────────────────


def select_lgas(
    tenant: str, *, full: bool = False, day: int | None = None,
) -> list[dict]:
    """LGAs to scan this run.

    full=True  → every LGA (initial seed sweep / on-demand full refresh).
    otherwise  → the rolling 1/REVISIT_DAYS slice that is "due" today, so every
                 LGA is refreshed once per Sentinel revisit while daily CDSE cost
                 stays bounded. The slice rotates by ordinal day, deterministic
                 and state-free (no per-LGA bookkeeping table needed).
    """
    lgas = _lga_index().get(tenant, [])
    if full or len(lgas) <= REVISIT_DAYS:
        return list(lgas)
    d = day if day is not None else date.today().toordinal()
    return [g for i, g in enumerate(lgas) if (i + d) % REVISIT_DAYS == 0]


async def _fetch_lga_series(
    client: SentinelStatisticalClient, lon: float, lat: float,
) -> tuple[list[float], list[float], date | None]:
    """Sentinel-2 NDVI + Sentinel-1 SAR series over a small box around one LGA
    centroid, oldest→newest. Mirrors the Farm Check query (per-pixel cloud
    masking on the optical pass)."""
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    bbox = bbox_around(lat, lon, LGA_BOX_HALF_M)
    ndvi_points = await client.compute_time_series(
        bbox=bbox, start=end - timedelta(days=LGA_NDVI_WINDOW_DAYS), end=end,
        dataset="sentinel-2-l2a", evalscript=EVALSCRIPT_S2_NDVI_CLOUDMASKED,
        max_cloud_cover_pct=None, resolution_deg=FARM_RESOLUTION_DEG,
    )
    sar_points = await client.compute_time_series(
        bbox=bbox, start=end - timedelta(days=LGA_SAR_WINDOW_DAYS), end=end,
        dataset="sentinel-1-grd", evalscript=EVALSCRIPT_S1_VV_DB,
        resolution_deg=FARM_RESOLUTION_DEG,
    )
    ndvi = [p.mean for p in ndvi_points if p.mean is not None]
    sar = [p.mean for p in sar_points if p.mean is not None]
    dates = [p.interval_from.date() for p in (ndvi_points + sar_points) if p.mean is not None]
    return ndvi, sar, (max(dates) if dates else None)


async def _nightlight_by_point(
    points: list[tuple[float, float]],
) -> dict[tuple[float, float], float]:
    """Map each point to its new-light-in-dark-area component (0..1) from current
    vs ~6-week-earlier VIIRS Black Marble radiance. Batched (tiles disk-cached)
    and best-effort: returns {} on any failure so a VIIRS hiccup never blocks the
    NDVI/SAR sweep. NASA data — separate from the CDSE budget."""
    s = get_settings()
    if not s.earthdata_token or not points:
        return {}
    anchor = (datetime.now(timezone.utc) - timedelta(days=VIIRS_LATENCY_DAYS)).date()
    kw = {
        "base_url": s.earthdata_laads_base_url,
        "collection": s.earthdata_laads_collection,
        "product": s.viirs_black_marble_product,
        "token": s.earthdata_token,
    }
    try:
        cur = await sample_radiance(
            points, day=anchor, max_lookback_days=VIIRS_LATENCY_DAYS + 8, **kw)
        base = await sample_radiance(
            points, day=anchor - timedelta(days=VIIRS_BASELINE_LAG_DAYS),
            max_lookback_days=12, **kw)
    except Exception as exc:  # noqa: BLE001 — VIIRS optional, never fail the sweep
        log.warning("encroachment nightlight sample failed: %s", exc)
        return {}
    out: dict[tuple[float, float], float] = {}
    for pt in points:
        c = cur.get(pt)
        b = base.get(pt)
        out[pt] = nightlight_newlight(
            c.radiance if c else None, b.radiance if b else None)
    return out


async def detect_per_lga_for_tenant(
    session: AsyncSession, client: SentinelStatisticalClient,
    tenant: str, *, full: bool = False, day: int | None = None,
) -> str:
    """Evaluate the due LGAs (rolling) or every LGA (full) from each one's OWN
    satellite series, refreshing each scanned LGA's auto-watch independently.

    Rolling, per-LGA: we delete only the *scanned* LGA's prior pending watch and
    re-insert if it still clears threshold — so un-scanned LGAs keep their
    current watch and the statewide map stays fully populated between revisits.
    Officer-actioned rows (acknowledged/resolved) are always preserved.
    """
    await set_tenant_schema(session, tenant)
    batch = select_lgas(tenant, full=full, day=day)
    if not batch:
        # No centroids for this tenant — fall back to the ROI signal.
        return await detect_for_tenant(session, tenant)

    # Year-round VIIRS new-light component for the whole batch in one go
    # (tile-cached, NASA — off the CDSE budget). {} if unavailable → 0 per LGA.
    nl_by_point = await _nightlight_by_point([(g["lon"], g["lat"]) for g in batch])

    alerts = 0
    evaluated = 0
    for g in batch:
        # Fetch FIRST — only refresh this LGA's watch on a SUCCESSFUL read, so a
        # rate-limit (429) or error skips the LGA without wiping its prior watch.
        try:
            ndvi, sar, latest = await _fetch_lga_series(client, g["lon"], g["lat"])
        except CopernicusError as exc:
            log.warning("encroachment per-LGA CDSE error tenant=%s lga=%s: %s",
                        tenant, g.get("lga"), exc)
            continue
        evaluated += 1
        nl = nl_by_point.get((g["lon"], g["lat"]), 0.0)
        signal = compute_encroachment(ndvi, sar, 0, latest, nightlight=nl)
        # Read succeeded → refresh THIS LGA only (delete prior, insert if it
        # still clears). A now-calm LGA simply loses its watch. Other LGAs keep
        # their current watch (rolling coverage).
        await session.execute(text(
            "DELETE FROM alert_events WHERE model_name = :m "
            "AND status = 'pending_review' AND lga = :lga"
        ), {"m": MODEL_VERSION, "lga": g["lga"]})
        if signal is None or signal.score < ALERT_THRESHOLD:
            continue
        h = hashlib.sha256(json.dumps(
            {"t": tenant, "lga": g["lga"], "obs": str(latest), "m": MODEL_VERSION},
            sort_keys=True,
        ).encode("utf-8")).hexdigest()
        await _insert_alert(
            session, tenant=tenant, signal=signal, input_hash=h, trace_id=uuid4(),
            lga_name=g["lga"], lon=g["lon"], lat=g["lat"], scope_label="LGA-level",
        )
        alerts += 1
    mode = "full" if full else "rolling"
    return f"{alerts} alert(s) / {evaluated} scanned ({mode}, {len(batch)} LGAs due)"


async def run_encroachment_sweep(
    tenants: list[str] | None = None, *, full: bool = False,
) -> dict[str, str]:
    """Run the detector across every pilot tenant. Failures are isolated.

    Uses the per-LGA sweep when CDSE credentials are configured (statewide
    coverage from live per-LGA satellite series); falls back to the ROI-level
    signal from satellite_observations when they are not (e.g. local/test).
    `full=True` scans every LGA (initial seed / on-demand); the default daily
    run scans the rolling revisit-due slice.
    """
    target = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    client = SentinelStatisticalClient(CopernicusClient())
    per_lga = client.configured
    day = date.today().toordinal()
    log.info("encroachment sweep starting (mode=%s, scope=%s, revisit=%dd)",
             "per-LGA" if per_lga else "ROI-fallback",
             "full" if full else "rolling", REVISIT_DAYS)
    out: dict[str, str] = {}
    for t in target:
        async with factory() as session:
            try:
                if per_lga:
                    out[t] = await detect_per_lga_for_tenant(
                        session, client, t, full=full, day=day)
                else:
                    out[t] = await detect_for_tenant(session, t)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 — isolate per tenant
                out[t] = f"failed: {exc!s}"
                log.exception("encroachment failed tenant=%s", t)
    log.info("encroachment sweep: %s", out)
    return out
