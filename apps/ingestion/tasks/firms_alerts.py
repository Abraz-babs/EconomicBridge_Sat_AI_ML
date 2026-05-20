"""Persist FIRMS alert candidates into tenant_<id>.alert_events.

Companion to `tasks.firms_ingest`. The ingest task writes raw detections
into `heat_signatures`; this task promotes the high-confidence subset
into `alert_events` — the table the dashboard actually reads.

Idempotent by design: `model_input_hash` is unique per (tenant, ~1km grid,
date, instrument) and we skip insertions where a row with that hash
already exists for the tenant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from processors.firms_to_alerts import AlertCandidate

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AlertWriteResult:
    """Counts returned to the caller."""

    candidates: int       # high-confidence detections produced by the processor
    inserted: int         # new alert_events rows
    skipped_duplicates: int  # candidates whose model_input_hash already existed
    skipped_capped: int = 0  # candidates dropped because per-run cap was hit


# Severity rank used to pick which candidates survive the per-run cap.
# Lower number = louder alert.
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


# Fire is a SECONDARY signal in the encroachment story. The Farmland
# Protection dashboard is centred on conflict prediction; a 30-pixel burn
# front turning into 30 alert rows drowns the conflict feed. Cap the
# scheduled FIRMS sweep to the top N fires per tenant per run and let the
# rest live in heat_signatures for the conflict model to consume.
DEFAULT_MAX_ALERTS_PER_RUN: int = 2


async def write_alert_candidates(
    session: AsyncSession,
    *,
    tenant_id: str,
    candidates: list[AlertCandidate],
    max_per_run: int = DEFAULT_MAX_ALERTS_PER_RUN,
) -> AlertWriteResult:
    """Insert candidates (capped + dedup'd) into the tenant alert_events.

    Selection rule:
      1. Sort by severity (critical first, low last), then confidence DESC.
      2. Take the top `max_per_run` candidates.
      3. For each, skip if a row with the same model_input_hash already
         exists (dedup across re-runs of the same FIRMS window).

    The rest stay in heat_signatures (already written by the upstream
    ingest task) so the conflict-prediction model can still consume them.
    """
    if not candidates:
        return AlertWriteResult(candidates=0, inserted=0, skipped_duplicates=0)

    ranked = sorted(
        candidates,
        key=lambda c: (
            _SEVERITY_RANK.get(c.severity, len(_SEVERITY_RANK)),
            -c.confidence_score,
        ),
    )
    survivors = ranked[: max(0, int(max_per_run))]
    dropped_by_cap = len(ranked) - len(survivors)

    await set_tenant_schema(session, tenant_id)

    inserted = 0
    skipped_dups = 0
    for c in survivors:
        if await _hash_exists(session, c.model_input_hash):
            skipped_dups += 1
            continue
        await _insert_alert(session, c)
        await session.commit()
        inserted += 1

    log.info(
        "firms.alerts tenant=%s candidates=%d inserted=%d "
        "skipped_dups=%d skipped_capped=%d",
        tenant_id, len(candidates), inserted, skipped_dups, dropped_by_cap,
    )
    return AlertWriteResult(
        candidates=len(candidates),
        inserted=inserted,
        skipped_duplicates=skipped_dups,
        skipped_capped=dropped_by_cap,
    )


async def _hash_exists(session: AsyncSession, model_input_hash: str) -> bool:
    """Return True if an alert_events row with this hash already exists."""
    result = await session.execute(
        text(
            "SELECT 1 FROM alert_events WHERE model_input_hash = :h LIMIT 1"
        ),
        {"h": model_input_hash},
    )
    return result.first() is not None


async def _insert_alert(session: AsyncSession, c: AlertCandidate) -> None:
    """Insert one alert_events row inside the active tenant schema.

    `search_path` must already be pinned to `tenant_<id>, public` by the
    caller via `set_tenant_schema`.
    """
    await session.execute(
        text(
            """
            INSERT INTO alert_events (
                tenant_id, alert_type, severity, status,
                location,
                confidence_score, affected_area_ha,
                livelihoods_at_risk, economic_value_ngn,
                predicted_breach_hours,
                satellite_source, satellite_pass_time,
                model_name, model_version, model_input_hash,
                human_review_required
            ) VALUES (
                :tenant_id, :alert_type, :severity, 'pending_review',
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :confidence_score, :affected_area_ha,
                :livelihoods_at_risk, :economic_value_ngn,
                :predicted_breach_hours,
                :satellite_source, :satellite_pass_time,
                :model_name, :model_version, :model_input_hash,
                :human_review_required
            )
            """
        ),
        {
            "tenant_id": c.tenant_id,
            "alert_type": c.alert_type,
            "severity": c.severity,
            "lon": c.longitude,
            "lat": c.latitude,
            "confidence_score": c.confidence_score,
            "affected_area_ha": c.affected_area_ha,
            "livelihoods_at_risk": c.livelihoods_at_risk,
            "economic_value_ngn": c.economic_value_ngn,
            "predicted_breach_hours": c.predicted_breach_hours,
            "satellite_source": c.satellite_source,
            "satellite_pass_time": c.satellite_pass_time,
            "model_name": c.model_name,
            "model_version": c.model_version,
            "model_input_hash": c.model_input_hash,
            "human_review_required": c.human_review_required,
        },
    )
