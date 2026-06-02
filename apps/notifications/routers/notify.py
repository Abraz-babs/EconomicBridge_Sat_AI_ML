"""POST /api/v1/notify/conflict — dispatch SMS for one alert/prediction.

Body validates against `NotifyConflictRequest`. Returns a per-subscriber
outcome list so the caller can see exactly who received what.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id
from dependencies import TENANT_HEADER, require_signed_dpa
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.notify import (
    DispatchSummary,
    NotifyConflictData,
    NotifyConflictRequest,
    OutboxListData,
    OutboxRow,
    SmsPreviewData,
)
from services.dispatcher import dispatch_conflict_alert
from services.messages import RenderContext, is_verified, render_conflict_sms
from services.providers import gateway_for_tenant
from sqlalchemy import text

router = APIRouter(prefix="/notify", tags=["notify"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.get(
    "/preview",
    response_model=SuccessResponse[SmsPreviewData],
    summary="Render a sample farmer SMS in a given language (no send, no PII)",
)
async def preview_sms(
    request: Request,
    lang: Annotated[str, Query()] = "en",
    tenant_id: Annotated[str, Query()] = "benue",
    severity: Annotated[str, Query()] = "critical",
    alert_type: Annotated[str, Query()] = "conflict",
    lga: Annotated[str | None, Query()] = None,
    eta_hours: Annotated[int | None, Query()] = 18,
    affected_area_ha: Annotated[float | None, Query()] = 120,
) -> SuccessResponse[SmsPreviewData]:
    """Demo/preview only — reuses the real renderer so the dashboard can show
    exactly what a farmer would receive in each language."""
    body = render_conflict_sms(
        RenderContext(
            tenant_id=tenant_id,
            severity=severity,
            alert_type=alert_type,
            lga=lga,
            zone_name=None,
            affected_area_ha=affected_area_ha,
            livelihoods_at_risk=None,
            eta_hours=eta_hours,
        ),
        lang,
    )
    return SuccessResponse(
        data=SmsPreviewData(
            language=lang, verified=is_verified(lang), body=body, chars=len(body),
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _mask_phone(phone: str) -> str:
    """Show only the last 4 digits — e.g. '••••0123'."""
    tail = phone[-4:] if len(phone) >= 4 else phone
    return f"••••{tail}"


@router.get(
    "/outbox",
    response_model=SuccessResponse[OutboxListData],
    summary="Recent queued/sent SMS for a tenant (DPA-gated; phone masked)",
    dependencies=[Depends(require_signed_dpa)],
)
async def recent_outbox(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> SuccessResponse[OutboxListData]:
    tenant_id = (request.headers.get(TENANT_HEADER) or "").strip().lower()
    rows = (
        await session.execute(
            text(
                """
                SELECT language, status, provider, severity, alert_type,
                       phone_e164, message, queued_at
                  FROM public.sms_outbox
                 WHERE tenant_id = :tenant
                 ORDER BY queued_at DESC
                 LIMIT :limit
                """
            ),
            {"tenant": tenant_id, "limit": limit},
        )
    ).mappings().all()
    out = [
        OutboxRow(
            language=r["language"],
            status=r["status"],
            provider=r["provider"],
            severity=r["severity"],
            alert_type=r["alert_type"],
            phone_masked=_mask_phone(r["phone_e164"]),
            message=r["message"],
            queued_at=r["queued_at"],
        )
        for r in rows
    ]
    return SuccessResponse(
        data=OutboxListData(rows=out),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


@router.post(
    "/conflict",
    response_model=SuccessResponse[NotifyConflictData],
    summary="Dispatch SMS alerts to subscribers for a conflict prediction or alert",
    description=(
        "**PII gate (Slice 17):** requires `X-Tenant-Id` + "
        "`X-Organisation-Id` matching a signed Data Processing "
        "Agreement. The endpoint dispatches real SMS to subscriber "
        "phone numbers — the highest-PII operation in the platform. "
        "The header `X-Tenant-Id` must match `body.tenant_id`."
    ),
    dependencies=[Depends(require_signed_dpa)],
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

    # The DPA gate validated X-Tenant-Id against a signed DPA. Require
    # body.tenant_id to match so a caller can't acquire a DPA for one
    # tenant then trigger an SMS blast against another via the body.
    header_tenant = (request.headers.get(TENANT_HEADER) or "").strip().lower()
    if header_tenant != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"X-Tenant-Id header ({header_tenant!r}) does not match "
                f"body.tenant_id ({tenant_id!r}). Both must refer to the "
                f"same pilot tenant."
            ),
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
