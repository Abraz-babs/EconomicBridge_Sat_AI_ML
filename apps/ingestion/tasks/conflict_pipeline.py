
"""Conflict prediction pipeline — Q1 product deliverable.

Daily flow per tenant:
  1. Read the last `lookback_days` of heat_signatures from the tenant
     schema.
  2. Cluster them on a 0.1° grid (see processors/conflict_features.py).
  3. For each cluster, count nearby historical alerts + decide
     "is_new_geography".
  4. Call ML at POST /predict/conflict over HTTP with the cluster's
     feature vector (the ML service persists to tenant_X.conflict_predictions).
  5. If the returned confidence clears settings.conflict_alert_min_confidence,
     also write an alert_events row with alert_type='conflict' so the
     dashboard surfaces it.
  6. Cap per tenant per run (settings.conflict_max_alerts_per_run) —
     same legibility logic as the FIRMS pipeline.

This is heuristic-first by design: several features in step 3 are
imputed (see processors/conflict_features.py). The contract that the
ML service satisfies is the same one a fully-labelled RF will satisfy
later — the pipeline above does not change when the model upgrades.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db import PILOT_TENANT_IDS, get_session_factory, is_valid_tenant_id, set_tenant_schema
from processors.conflict_features import (
    MODEL_VERSION_LABEL,
    DetectionCluster,
    HeatDetection,
    clusters_from_detections,
)
from sources.ml_client import MLConflictPrediction, MLError, predict_conflict

log = logging.getLogger(__name__)

# How far back we sweep heat_signatures when building features.
DEFAULT_LOOKBACK_DAYS: int = 7

# Conflict-risk mapping — pulled once at import. Keep this in sync with
# the tenants.yaml file; this is a deliberate trade-off (avoiding a
# yaml parser at hot-path runtime).
_TENANT_CONFLICT_RISK: dict[str, str] = {
    "kebbi":    "critical",
    "benue":    "critical",
    "plateau":  "critical",
    "kaduna":   "high",
    "niger":    "high",
    "zamfara":  "critical",
    "fct":      "medium",
    "nasarawa": "high",
    "ghana":    "high",
    "senegal":  "medium",
}


# ─── Result dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TenantConflictResult:
    """Summary returned per tenant to the caller."""

    tenant_id: str
    clusters_built: int
    predictions_made: int
    alerts_written: int
    skipped_below_threshold: int
    skipped_capped: int
    skipped_duplicates: int
    error: str | None = None


# ─── DB helpers ────────────────────────────────────────────────────────────


async def _recent_heat_detections(
    session: AsyncSession, *, tenant_id: str, lookback_days: int
) -> list[HeatDetection]:
    """Pull recent heat_signatures into the typed projection used by the
    feature extractor. Returns an empty list when the tenant has none."""
    await set_tenant_schema(session, tenant_id)
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text AS id,
                       ST_Y(location) AS lat,
                       ST_X(location) AS lon,
                       brightness_k
                  FROM heat_signatures
                 WHERE detected_at > NOW() - make_interval(days => :days)
                """
            ),
            {"days": int(lookback_days)},
        )
    ).mappings().all()
    return [
        HeatDetection(
            detection_id=row["id"],
            latitude=float(row["lat"]),
            longitude=float(row["lon"]),
            brightness_k=(
                float(row["brightness_k"])
                if row["brightness_k"] is not None
                else None
            ),
        )
        for row in rows
    ]


async def _historical_incident_count(
    session: AsyncSession, *, tenant_id: str, days: int = 365
) -> int:
    """COUNT conflict alerts within the trailing `days` for is_new_geography
    and historical_incidents features."""
    await set_tenant_schema(session, tenant_id)
    return (
        await session.execute(
            text(
                """
                SELECT COUNT(*)
                  FROM alert_events
                 WHERE alert_type = 'conflict'
                   AND NOT is_deleted
                   AND created_at > NOW() - make_interval(days => :days)
                """
            ),
            {"days": int(days)},
        )
    ).scalar_one()


async def _prior_alert_points(
    session: AsyncSession, *, tenant_id: str
) -> list[tuple[float, float]]:
    """Coords of every past conflict alert (used for is_new_geography)."""
    await set_tenant_schema(session, tenant_id)
    rows = (
        await session.execute(
            text(
                """
                SELECT ST_Y(location) AS lat, ST_X(location) AS lon
                  FROM alert_events
                 WHERE alert_type = 'conflict' AND NOT is_deleted
                   AND location IS NOT NULL
                """
            )
        )
    ).all()
    return [(float(r[0]), float(r[1])) for r in rows]


async def _hash_exists(
    session: AsyncSession, *, model_input_hash: str
) -> bool:
    """Dedup guard — only one alert per (cluster, day, model_version)."""
    result = await session.execute(
        text(
            "SELECT 1 FROM alert_events "
            "WHERE model_input_hash = :h LIMIT 1"
        ),
        {"h": model_input_hash},
    )
    return result.first() is not None


# ─── Severity bucketing ───────────────────────────────────────────────────


def severity_for(prediction: float) -> str:
    """Map a 0..1 conflict probability to the four severity bands."""
    if prediction >= 0.85:
        return "critical"
    if prediction >= 0.70:
        return "high"
    if prediction >= 0.55:
        return "medium"
    return "low"


# ─── Hashing for dedup ────────────────────────────────────────────────────


def _build_input_hash(
    *,
    cluster: DetectionCluster,
    model_version: str,
    bucket_date: str,
) -> str:
    """SHA-256 of (cluster_id | bucket_date | model_version). Same cluster
    on the same day with the same model => same hash => dedup."""
    payload = json.dumps(
        {
            "cluster_id": cluster.cluster_id,
            "bucket_date": bucket_date,
            "model_version": model_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─── Alert insertion ──────────────────────────────────────────────────────


async def _insert_conflict_alert(
    session: AsyncSession,
    *,
    tenant_id: str,
    cluster: DetectionCluster,
    prediction: MLConflictPrediction,
    model_input_hash: str,
    trace_id: UUID,
) -> UUID:
    """Insert one row in tenant_X.alert_events. Returns the new alert id."""
    alert_id = uuid4()
    zone_name = (
        f"Heat cluster · {cluster.detection_count} VIIRS/MODIS pixels "
        f"near {cluster.centroid_lat:.3f}°N {cluster.centroid_lon:.3f}°E"
    )
    sev = severity_for(prediction.prediction)

    await session.execute(
        text(
            """
            INSERT INTO alert_events (
                id, tenant_id, alert_type, severity, status,
                zone_name, lga,
                location,
                confidence_score,
                affected_area_ha, livelihoods_at_risk, economic_value_ngn,
                predicted_breach_hours,
                satellite_source, satellite_pass_time,
                model_name, model_version, model_input_hash,
                shap_values,
                human_review_required,
                created_at, updated_at, created_by
            ) VALUES (
                :id, :tenant_id, 'conflict', :severity, 'pending_review',
                :zone_name, NULL,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :confidence,
                NULL, NULL, NULL,
                NULL,
                :sat_source, NOW(),
                :model_name, :model_version, :model_input_hash,
                CAST(:shap AS JSONB),
                :requires_review,
                NOW(), NOW(), :trace_id
            )
            """
        ),
        {
            "id": alert_id,
            "tenant_id": tenant_id,
            "severity": sev,
            "zone_name": zone_name,
            "lon": cluster.centroid_lon,
            "lat": cluster.centroid_lat,
            "confidence": prediction.prediction,
            "sat_source": (
                f"NASA FIRMS / cluster of {cluster.detection_count} detections "
                f"(predictor v{prediction.model_version})"
            ),
            "model_name": prediction.model_name,
            "model_version": prediction.model_version,
            "model_input_hash": model_input_hash,
            "shap": json.dumps(prediction.shap_values),
            "requires_review": prediction.requires_human_review,
            "trace_id": trace_id,
        },
    )
    return alert_id


# ─── Top-level entry point ────────────────────────────────────────────────


async def run_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    trace_id: UUID | None = None,
    now: datetime | None = None,
) -> TenantConflictResult:
    """One full pass for a tenant. Caller owns the session."""
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")

    settings = get_settings()
    trace = trace_id or uuid4()
    today = (now or datetime.now(timezone.utc)).date().isoformat()

    detections = await _recent_heat_detections(
        session, tenant_id=tenant_id, lookback_days=lookback_days
    )
    history = await _historical_incident_count(session, tenant_id=tenant_id)
    prior_points = await _prior_alert_points(session, tenant_id=tenant_id)

    clusters = clusters_from_detections(
        tenant_id=tenant_id,
        detections=detections,
        tenant_conflict_risk=_TENANT_CONFLICT_RISK.get(tenant_id),
        historical_incident_count=int(history),
        prior_alert_points=prior_points,
    )

    if not clusters:
        return TenantConflictResult(
            tenant_id=tenant_id,
            clusters_built=0,
            predictions_made=0,
            alerts_written=0,
            skipped_below_threshold=0,
            skipped_capped=0,
            skipped_duplicates=0,
        )

    # Score every cluster, then cap.
    scored: list[tuple[DetectionCluster, MLConflictPrediction]] = []
    predictions_made = 0
    for cluster in clusters:
        try:
            pred = await predict_conflict(
                tenant_id=tenant_id,
                heat_signature_intensity=cluster.heat_signature_intensity,
                boundary_distance_km=cluster.boundary_distance_km,
                ndvi_delta=cluster.ndvi_delta,
                herder_density=cluster.herder_density,
                historical_incidents=cluster.historical_incidents,
                rainfall_anomaly=cluster.rainfall_anomaly,
                is_new_geography=cluster.is_new_geography,
                lat=cluster.centroid_lat,
                lon=cluster.centroid_lon,
                zone_name=(
                    f"Heat cluster · {cluster.detection_count} detections "
                    f"near {cluster.centroid_lat:.3f},{cluster.centroid_lon:.3f}"
                ),
                # ML's persist=True path has a bug when lga is NULL — asyncpg
                # can't infer the param type for NULL VARCHAR. Audit goes
                # through alert_events for now; conflict_predictions backfill
                # is a follow-up (fix CASTs in apps/ml/routers/predict.py).
                persist=False,
            )
            predictions_made += 1
            scored.append((cluster, pred))
        except MLError as exc:
            log.exception(
                "conflict.predict FAILED tenant=%s cluster=%s: %s",
                tenant_id, cluster.cluster_id, exc,
            )

    # Filter to alert-worthy predictions and rank by confidence DESC.
    eligible = [
        (c, p) for (c, p) in scored
        if p.confidence >= settings.conflict_alert_min_confidence
    ]
    below_threshold = len(scored) - len(eligible)
    eligible.sort(key=lambda cp: cp[1].confidence, reverse=True)

    cap = max(0, int(settings.conflict_max_alerts_per_run))
    survivors = eligible[:cap]
    dropped_by_cap = max(0, len(eligible) - cap)

    # Persist alert_events for the survivors.
    await set_tenant_schema(session, tenant_id)
    alerts_written = 0
    skipped_duplicates = 0
    for cluster, prediction in survivors:
        h = _build_input_hash(
            cluster=cluster,
            model_version=prediction.model_version,
            bucket_date=today,
        )
        if await _hash_exists(session, model_input_hash=h):
            skipped_duplicates += 1
            continue
        await _insert_conflict_alert(
            session,
            tenant_id=tenant_id,
            cluster=cluster,
            prediction=prediction,
            model_input_hash=h,
            trace_id=trace,
        )
        await session.commit()
        alerts_written += 1

    log.info(
        "conflict.pipeline tenant=%s clusters=%d preds=%d wrote=%d "
        "below_thresh=%d capped=%d dups=%d",
        tenant_id, len(clusters), predictions_made, alerts_written,
        below_threshold, dropped_by_cap, skipped_duplicates,
    )
    return TenantConflictResult(
        tenant_id=tenant_id,
        clusters_built=len(clusters),
        predictions_made=predictions_made,
        alerts_written=alerts_written,
        skipped_below_threshold=below_threshold,
        skipped_capped=dropped_by_cap,
        skipped_duplicates=skipped_duplicates,
    )


async def run_daily_conflict_pipeline(
    tenants: list[str] | None = None,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Cron entry-point — iterate every pilot tenant. Per-tenant failures
    do not abort the sweep."""
    target = tenants if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    summary: dict[str, Any] = {}
    started = time.monotonic()

    for tenant_id in target:
        async with factory() as session:
            try:
                result = await run_for_tenant(
                    session,
                    tenant_id=tenant_id,
                    lookback_days=lookback_days,
                )
                summary[tenant_id] = {
                    "clusters": result.clusters_built,
                    "alerts_written": result.alerts_written,
                    "below_threshold": result.skipped_below_threshold,
                    "capped": result.skipped_capped,
                }
            except Exception as exc:  # noqa: BLE001
                summary[tenant_id] = {"error": str(exc)}
                log.exception(
                    "conflict.pipeline tenant=%s FAILED: %s", tenant_id, exc
                )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "conflict.pipeline summary (model_version=%s) duration_ms=%d %s",
        MODEL_VERSION_LABEL, elapsed_ms, summary,
    )
    return summary
