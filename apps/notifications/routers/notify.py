"""POST /api/v1/notify/conflict — dispatch SMS for one alert/prediction.

Body validates against `NotifyConflictRequest`. Returns a per-subscriber
outcome list so the caller can see exactly who received what.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.notify import (
    DispatchSummary,
    NotifyConflictData,
    NotifyConflictRequest,
)
from services.dispatcher import dispatch_conflict_alert
from services.messages import RenderContext, render_conflict_sms
from services.providers import gateway_for_tenant

router = APIRouter(prefix="/notify", tags=["notify"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/conflict",
    response_model=SuccessResponse[NotifyConflictData],
    summary="Dispatch SMS alerts to subscribers for a conflict prediction or alert",
)
async def notify_conflict(
    body: NotifyConflictRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[NotifyConflictData]:
    tenant_id = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tenant_id!r}",
        )

    trace = _trace_id(request)
    outcomes = await dispatch_conflict_alert(
        session,
        tenant_id=tenant_id,
        severity=body.severity.value,
        alert_type=body.alert_type.value,
        lga=body.lga,
        zone_name=body.zone_name,
        affected_area_ha=body.affected_area_ha,
        livelihoods_at_risk=body.livelihoods_at_risk,
        eta_hours=body.eta_hours,
        related_prediction_id=body.prediction_id,
        related_alert_id=body.alert_id,
        trace_id=trace,
    )

    # Render the message once more (cheap, deterministic) just for the response
    # — the dispatcher already used the same body to actually send.
    rendered = render_conflict_sms(
        RenderContext(
            tenant_id=tenant_id,
            severity=body.severity.value,
            alert_type=body.alert_type.value,
            lga=body.lga,
            zone_name=body.zone_name,
            affected_area_ha=body.affected_area_ha,
            livelihoods_at_risk=body.livelihoods_at_risk,
            eta_hours=body.eta_hours,
        )
    )

    dispatched = sum(1 for o in outcomes if o.status in {"sent", "delivered", "mock"})
    skipped = sum(1 for o in outcomes if o.skipped_duplicate)
    failed = sum(1 for o in outcomes if o.status == "failed")

    return SuccessResponse(
        data=NotifyConflictData(
            tenant_id=tenant_id,
            severity=body.severity.value,
            matched_subscribers=len(outcomes),
            dispatched=dispatched,
            skipped_duplicate=skipped,
            failed=failed,
            provider_chosen=gateway_for_tenant(tenant_id),
            rendered_message=rendered,
            dispatches=[
                DispatchSummary(
                    subscriber_id=o.subscriber_id,
                    phone_e164=o.phone_e164,
                    provider=o.provider,
                    status=o.status,
                    provider_message_id=o.provider_message_id,
                    error_message=o.error_message,
                )
                for o in outcomes
            ],
        ),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=trace,
            timestamp=datetime.now(timezone.utc),
        ),
    )
