"""GET /api/v1/farmland/alerts — list alerts for the active tenant.

Tenant scoping is delivered by middleware/tenant.py + db/engine.get_session.
This endpoint requires the X-Tenant-Id header — without it the underlying
session has no search_path set and queries against alert_events fail (the
table does not exist in `public`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import Pagination, ResponseMeta, SuccessResponse
from schemas.farmland import (
    AlertListData,
    AlertListQuery,
    AlertResponse,
    AlertSeverity,
    AlertStatus,
    AlertStatusPatch,
    AlertType,
    FireStatusData,
)
from services import farmland as farmland_service
from services.auto_notify import fire_conflict_notification

router = APIRouter(prefix="/farmland", tags=["farmland"])

# Status that means "an officer reviewed + approved this alert" — the gate for
# auto-dispatching farmer SMS (fire alerts are human_review_required by design).
NOTIFY_ON_STATUS = "acknowledged"


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required for this endpoint",
        )
    return tenant_id


@router.get(
    "/alerts",
    response_model=SuccessResponse[AlertListData],
    summary="List farmland alerts for a tenant",
    description=(
        "Returns alerts from `tenant_<id>.alert_events`, paginated and filterable. "
        "The `X-Tenant-Id` header selects the tenant (e.g. `kebbi`, `zamfara`)."
    ),
)
async def list_alerts(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1, le=10_000, description="1-indexed page")] = 1,
    per_page: Annotated[int, Query(ge=1, le=100, description="Page size, max 100")] = 20,
    severity: Annotated[
        list[AlertSeverity] | None,
        Query(description="Filter by severity. Repeat for OR semantics."),
    ] = None,
    status_: Annotated[
        list[AlertStatus] | None,
        Query(alias="status", description="Filter by alert status."),
    ] = None,
    alert_type: Annotated[
        list[AlertType] | None,
        Query(description="Filter by alert type (conflict, flood, ...)."),
    ] = None,
    lga: Annotated[
        str | None,
        Query(max_length=120, description="Exact LGA match."),
    ] = None,
    since: Annotated[
        datetime | None, Query(description="Inclusive lower bound on created_at.")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Inclusive upper bound on created_at.")
    ] = None,
    include_deleted: Annotated[
        bool, Query(description="Admin-only — return soft-deleted rows.")
    ] = False,
) -> SuccessResponse[AlertListData]:
    """List alerts for the active tenant."""
    # Side-effect: raises HTTPException if X-Tenant-Id is missing.
    _require_tenant(request)

    if since and until and since > until:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`since` must be earlier than or equal to `until`",
        )

    query = AlertListQuery(
        page=page,
        per_page=per_page,
        severity=severity,
        status=status_,
        alert_type=alert_type,
        lga=lga,
        since=since,
        until=until,
        include_deleted=include_deleted,
    )

    alerts, total = await farmland_service.list_alerts(session, query)

    return SuccessResponse(
        data=AlertListData(alerts=alerts),
        meta=ResponseMeta(
            tenant_id=None,  # meta.tenant_id is reserved for UUID-typed tenant ids
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=Pagination(page=page, per_page=per_page, total=total),
        ),
    )


@router.get(
    "/fire-status",
    response_model=SuccessResponse[FireStatusData],
    summary="Live NASA FIRMS fire-monitoring status for a tenant",
    description=(
        "How recently the daily FIRMS feed ran for this tenant and how many "
        "fire detections it has over the ROI (last 24h / 7 days). Lets the "
        "Farmland panel show the fire feed is monitored even out of fire "
        "season (detections are seasonally low in the wet months)."
    ),
)
async def fire_status(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[FireStatusData]:
    """Surface the live FIRMS feed status (last scan + recent detection counts)."""
    tenant_id = _require_tenant(request)

    last_scan_at = (await session.execute(
        text(
            "SELECT MAX(finished_at) FROM public.ingestion_runs "
            "WHERE tenant_id = :t AND status = 'succeeded' "
            "AND (source LIKE 'MODIS%' OR source LIKE 'VIIRS%')"
        ),
        {"t": tenant_id},
    )).scalar()

    # heat_signatures lives in the tenant schema (search_path set by get_session).
    # Guard so a tenant without the table degrades to zero rather than erroring.
    detections_24h = detections_7d = 0
    try:
        detections_24h = int((await session.execute(text(
            "SELECT count(*) FROM heat_signatures "
            "WHERE detected_at > now() - interval '24 hours'"
        ))).scalar() or 0)
        detections_7d = int((await session.execute(text(
            "SELECT count(*) FROM heat_signatures "
            "WHERE detected_at > now() - interval '7 days'"
        ))).scalar() or 0)
    except Exception:  # noqa: BLE001 — status indicator must never 500 the panel
        pass

    return SuccessResponse(
        data=FireStatusData(
            last_scan_at=last_scan_at,
            detections_24h=detections_24h,
            detections_7d=detections_7d,
        ),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


@router.patch(
    "/alerts/{alert_id}",
    response_model=SuccessResponse[AlertResponse],
    summary="Update an alert's lifecycle status",
    description=(
        "Transition an existing alert (e.g. mark `resolved` after mediation). "
        "Only the `status` field is mutable through this endpoint. "
        "The `X-Tenant-Id` header is required."
    ),
)
async def patch_alert(
    request: Request,
    alert_id: UUID,
    body: AlertStatusPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AlertResponse]:
    """Update one alert's status field."""
    _require_tenant(request)
    updated = await farmland_service.update_alert_status(session, alert_id, body.status)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found in active tenant",
        )

    # Auto-trigger farmer SMS only when an officer APPROVES the alert
    # (acknowledged) — never on raw detection, since FIRMS fire alerts are
    # human_review_required (legitimate ag burning looks like wildfire).
    # Best-effort + flag-gated; deduped per alert so re-acknowledging is a no-op.
    if updated.status == NOTIFY_ON_STATUS:
        await fire_conflict_notification(
            tenant_id=updated.tenant_id,
            # str-enum members serialise to their value ('critical', 'fire') in
            # JSON, so pass them through directly (str(enum) would give the repr).
            severity=updated.severity,
            alert_type=updated.alert_type,  # 'fire'
            lga=updated.lga,
            zone_name=updated.zone_name,
            affected_area_ha=updated.affected_area_ha,
            livelihoods_at_risk=updated.livelihoods_at_risk,
            eta_hours=updated.predicted_breach_hours,
            alert_id=updated.id,
        )

    return SuccessResponse(
        data=updated,
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )
