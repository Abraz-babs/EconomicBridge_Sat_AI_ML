"""Heat-signature ingestion task.

Queue-agnostic: the function `ingest_firms_for_tenant` is a plain async
coroutine that any caller (manual trigger router, Celery worker, cron driver)
can invoke. When Redis + Celery land we will wrap this body in a
`@celery_app.task` decorator — the body itself does not change.

Lifecycle, all inside a single DB transaction:
  1. INSERT a `public.ingestion_runs` row with status='running'
  2. fetch detections from NASA FIRMS (or mock if no MAP_KEY)
  3. INSERT one `tenant_<id>.heat_signatures` row per detection
  4. UPDATE the ingestion_runs row with status='succeeded' + counts
  5. on exception: UPDATE the run to status='failed' + error_message
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import is_valid_tenant_id, set_tenant_schema
from processors.firms_to_alerts import firms_to_alerts
from sources.nasa_firms import PILOT_BBOX, FirmsClient, FirmsDetection, FirmsError
from tasks.firms_alerts import AlertWriteResult, write_alert_candidates

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary returned to the caller."""

    run_id: UUID
    source: str
    tenant_id: str
    status: str
    records_ingested: int
    duration_ms: int
    started_at: datetime
    finished_at: datetime | None
    dry_run: bool
    error_message: str | None
    # Populated when generate_alerts=True; None otherwise. Keeps the
    # heat-signature counts and the alert-promotion counts disambiguated.
    alerts: AlertWriteResult | None = None


async def ingest_firms_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    source: str | None = None,
    day_range: int = 1,
    trace_id: UUID | None = None,
    trigger: str = "manual",
    dry_run: bool = False,
    generate_alerts: bool = False,
    client: FirmsClient | None = None,
) -> IngestResult:
    """Run one FIRMS pull for `tenant_id` and persist the detections.

    The caller owns the AsyncSession (typical: FastAPI dependency or a
    background-task wrapper). This function commits its own bookkeeping and
    returns when the work is durable.
    """
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"unknown tenant_id: {tenant_id!r}")
    bbox = PILOT_BBOX[tenant_id]
    firms = client or FirmsClient()
    src_label = source or firms._settings.nasa_firms_default_source  # noqa: SLF001
    run_id = uuid4()
    started_at = datetime.now(timezone.utc)
    started_ms = time.monotonic()

    await _insert_run(
        session,
        run_id=run_id,
        source=src_label,
        tenant_id=tenant_id,
        trigger=trigger,
        trace_id=trace_id,
        dry_run=dry_run,
        started_at=started_at,
    )
    await session.commit()

    try:
        detections = await firms.fetch(
            bbox=bbox, source=source, day_range=day_range
        )
    except FirmsError as exc:
        await _finalise_run(
            session, run_id=run_id,
            status="failed", records=0,
            duration_ms=int((time.monotonic() - started_ms) * 1000),
            error_message=str(exc)[:500],
        )
        await session.commit()
        raise

    inserted = 0
    if not dry_run and detections:
        await set_tenant_schema(session, tenant_id)
        inserted = await _bulk_insert_detections(
            session, tenant_id=tenant_id, run_id=run_id, detections=detections
        )

    alert_result: AlertWriteResult | None = None
    if generate_alerts and not dry_run and detections:
        candidates = firms_to_alerts(detections, tenant_id=tenant_id)
        alert_result = await write_alert_candidates(
            session, tenant_id=tenant_id, candidates=candidates
        )

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    finished_at = datetime.now(timezone.utc)
    await _finalise_run(
        session,
        run_id=run_id,
        status="succeeded",
        records=inserted if not dry_run else len(detections),
        duration_ms=duration_ms,
        finished_at=finished_at,
    )
    await session.commit()

    log.info(
        "firms.ingest tenant=%s source=%s records=%d alerts_inserted=%s "
        "duration_ms=%d dry_run=%s",
        tenant_id, src_label, inserted,
        alert_result.inserted if alert_result else "n/a",
        duration_ms, dry_run,
    )
    return IngestResult(
        run_id=run_id,
        source=src_label,
        tenant_id=tenant_id,
        status="succeeded",
        records_ingested=inserted if not dry_run else len(detections),
        duration_ms=duration_ms,
        started_at=started_at,
        finished_at=finished_at,
        dry_run=dry_run,
        error_message=None,
        alerts=alert_result,
    )


# ─── DB helpers ────────────────────────────────────────────────────────────


async def _insert_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    source: str,
    tenant_id: str,
    trigger: str,
    trace_id: UUID | None,
    dry_run: bool,
    started_at: datetime,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.ingestion_runs (
                id, source, tenant_id, trigger,
                started_at, status, dry_run, trace_id
            ) VALUES (
                :id, :source, :tenant_id, :trigger,
                :started_at, 'running', :dry_run, :trace_id
            )
            """
        ),
        {
            "id": run_id,
            "source": source,
            "tenant_id": tenant_id,
            "trigger": trigger,
            "started_at": started_at,
            "dry_run": dry_run,
            "trace_id": trace_id,
        },
    )


async def _finalise_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    status: str,
    records: int,
    duration_ms: int,
    finished_at: datetime | None = None,
    error_message: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE public.ingestion_runs
            SET status = :status,
                records_ingested = :records,
                duration_ms = :duration_ms,
                finished_at = COALESCE(:finished_at, NOW()),
                error_message = :error_message
            WHERE id = :id
            """
        ),
        {
            "id": run_id,
            "status": status,
            "records": records,
            "duration_ms": duration_ms,
            "finished_at": finished_at,
            "error_message": error_message,
        },
    )


async def _bulk_insert_detections(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: UUID,
    detections: list[FirmsDetection],
) -> int:
    """Insert detections into `tenant_<id>.heat_signatures`.

    `search_path` must already be set by the caller via `set_tenant_schema`.
    Uses executemany-style binding for efficiency.
    """
    payload = [
        {
            "tenant_id": tenant_id,
            "source": _source_label_for(d),
            "satellite": d.satellite,
            "instrument": d.instrument,
            "detected_at": d.detected_at,
            "lon": d.longitude,
            "lat": d.latitude,
            "brightness_k": d.brightness_k,
            "bright_t31_k": d.bright_t31_k,
            "scan": d.scan,
            "track": d.track,
            "frp": d.frp,
            "confidence": (d.confidence[:20] if d.confidence else None),
            "daynight": d.daynight,
            "run_id": run_id,
            "raw_payload": json.dumps(d.raw),
        }
        for d in detections
    ]
    if not payload:
        return 0

    await session.execute(
        text(
            """
            INSERT INTO heat_signatures (
                tenant_id, source, satellite, instrument,
                detected_at, location,
                brightness_k, bright_t31_k, scan, track, frp,
                confidence, daynight,
                ingestion_run_id, raw_payload
            ) VALUES (
                :tenant_id, :source, :satellite, :instrument,
                :detected_at,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :brightness_k, :bright_t31_k, :scan, :track, :frp,
                :confidence, :daynight,
                :run_id, CAST(:raw_payload AS JSONB)
            )
            """
        ),
        payload,
    )
    return len(payload)


def _source_label_for(d: FirmsDetection) -> str:
    """Compose a stable source label like 'MODIS_TERRA' or 'VIIRS_SUOMI-NPP'."""
    inst = (d.instrument or "UNKNOWN").upper()
    sat = (d.satellite or "UNKNOWN").upper()
    return f"{inst}_{sat}"[:50]
