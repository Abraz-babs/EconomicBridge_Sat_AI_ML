"""POST /api/v1/ingest/firms — manual ingestion trigger.

Runs synchronously today. Once Celery + Redis are wired this endpoint should
return 202 Accepted with a job_id and the work moves to a worker process; the
actual ingestion code in `tasks.firms_ingest` does not change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id
from tasks.firms_ingest import IngestResult, ingest_firms_for_tenant

router = APIRouter(prefix="/ingest", tags=["ingest"])


class FirmsTriggerRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=50)
    source: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "FIRMS source key (e.g. MODIS_NRT, VIIRS_SNPP_NRT). "
            "Defaults to MODIS_NRT."
        ),
    )
    # NASA caps NRT endpoints at 5 days (archive endpoint allows 10, but we
    # only use NRT here). Going above 5 returns a 400.
    day_range: int = Field(default=1, ge=1, le=5)
    dry_run: bool = False
    generate_alerts: bool = Field(
        default=False,
        description=(
            "If true, promote high-confidence detections into "
            "tenant_<id>.alert_events so the farmland dashboard shows them."
        ),
    )


class AlertWriteSummary(BaseModel):
    candidates: int
    inserted: int
    skipped_duplicates: int


class FirmsTriggerResponse(BaseModel):
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
    alerts: AlertWriteSummary | None = None


def _to_response(result: IngestResult) -> FirmsTriggerResponse:
    alerts: AlertWriteSummary | None = None
    if result.alerts is not None:
        alerts = AlertWriteSummary(
            candidates=result.alerts.candidates,
            inserted=result.alerts.inserted,
            skipped_duplicates=result.alerts.skipped_duplicates,
        )
    return FirmsTriggerResponse(
        run_id=result.run_id,
        source=result.source,
        tenant_id=result.tenant_id,
        status=result.status,
        records_ingested=result.records_ingested,
        duration_ms=result.duration_ms,
        started_at=result.started_at,
        finished_at=result.finished_at,
        dry_run=result.dry_run,
        error_message=result.error_message,
        alerts=alerts,
    )


@router.post(
    "/firms",
    response_model=FirmsTriggerResponse,
    summary="Manually trigger a NASA FIRMS pull for a tenant",
)
async def trigger_firms(
    request: Request,
    body: FirmsTriggerRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FirmsTriggerResponse:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )

    trace_id: UUID = getattr(request.state, "trace_id", uuid4())

    try:
        result = await ingest_firms_for_tenant(
            session,
            tenant_id=tenant_id,
            source=body.source,
            day_range=body.day_range,
            dry_run=body.dry_run,
            generate_alerts=body.generate_alerts,
            trace_id=trace_id,
            trigger="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_response(result)
