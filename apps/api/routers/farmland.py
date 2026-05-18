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
)
from services import farmland as farmland_service

router = APIRouter(prefix="/farmland", tags=["farmland"])


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
    tenant_id = _require_tenant(request)

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
    return SuccessResponse(
        data=updated,
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )
