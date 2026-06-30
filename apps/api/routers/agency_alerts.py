"""Admin endpoints for government-agency EMAIL alert subscriptions.

Super-admin registers a responsible agency (by email) to the alerts relevant to
its duty for a tenant + module, and can trigger a digest send on demand. The
scheduled path runs scripts.send_agency_alerts. SMS is a separate, deferred
channel. All routes gated by require_super_admin.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from dependencies import CurrentUser, require_super_admin
from schemas.envelope import ResponseMeta, SuccessResponse
from services.agency_alerts import send_agency_digests


router = APIRouter(prefix="/admin/agency-alerts", tags=["agency-alerts"])

Module = Literal["farmland", "shockguard", "cropguard"]
Severity = Literal["critical", "high", "medium", "all"]


class AgencySubIn(BaseModel):
    agency_name: str = Field(min_length=2, max_length=160)
    recipient_email: str = Field(min_length=5, max_length=200)
    tenant_id: str = Field(min_length=2, max_length=50)
    module: Module
    severity_threshold: Severity = "high"


class AgencySubRow(BaseModel):
    id: UUID
    agency_name: str
    recipient_email: str
    tenant_id: str
    module: str
    severity_threshold: str
    is_active: bool
    last_notified_at: datetime | None = None
    created_at: datetime


class AgencySubListData(BaseModel):
    subscriptions: list[AgencySubRow] = Field(default_factory=list)


class SendResultData(BaseModel):
    results: list[dict] = Field(default_factory=list)


def _meta() -> ResponseMeta:
    return ResponseMeta(tenant_id=None, trace_id=uuid4(),
                        timestamp=datetime.now(timezone.utc))


@router.post(
    "/subscriptions",
    response_model=SuccessResponse[AgencySubRow],
    summary="Register (or re-activate) a government agency for email alerts",
)
async def create_subscription(
    body: AgencySubIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[AgencySubRow]:
    await session.execute(text("SET search_path TO public"))
    row = (await session.execute(text(
        """
        INSERT INTO agency_alert_subscriptions
            (id, agency_name, recipient_email, tenant_id, module, severity_threshold)
        VALUES (:id, :agency, :email, :tenant, :module, :sev)
        ON CONFLICT (tenant_id, module, recipient_email) DO UPDATE
            SET agency_name = EXCLUDED.agency_name,
                severity_threshold = EXCLUDED.severity_threshold,
                is_active = TRUE
        RETURNING id, agency_name, recipient_email, tenant_id, module,
                  severity_threshold, is_active, last_notified_at, created_at
        """
    ), {
        "id": uuid4(), "agency": body.agency_name.strip(),
        "email": body.recipient_email.strip().lower(),
        "tenant": body.tenant_id.strip().lower(),
        "module": body.module, "sev": body.severity_threshold,
    })).mappings().one()
    await session.commit()
    return SuccessResponse(data=AgencySubRow(**dict(row)), meta=_meta())


@router.get(
    "/subscriptions",
    response_model=SuccessResponse[AgencySubListData],
    summary="List government-agency alert subscriptions",
)
async def list_subscriptions(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[AgencySubListData]:
    await session.execute(text("SET search_path TO public"))
    rows = (await session.execute(text(
        "SELECT id, agency_name, recipient_email, tenant_id, module, "
        "severity_threshold, is_active, last_notified_at, created_at "
        "FROM agency_alert_subscriptions ORDER BY agency_name, tenant_id, module"
    ))).mappings().all()
    return SuccessResponse(
        data=AgencySubListData(subscriptions=[AgencySubRow(**dict(r)) for r in rows]),
        meta=_meta(),
    )


@router.delete(
    "/subscriptions/{sub_id}",
    response_model=SuccessResponse[AgencySubListData],
    summary="Deactivate an agency alert subscription",
)
async def deactivate_subscription(
    sub_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[AgencySubListData]:
    await session.execute(text("SET search_path TO public"))
    await session.execute(text(
        "UPDATE agency_alert_subscriptions SET is_active = FALSE WHERE id = :id"
    ), {"id": sub_id})
    await session.commit()
    return SuccessResponse(data=AgencySubListData(), meta=_meta())


@router.post(
    "/send",
    response_model=SuccessResponse[SendResultData],
    summary="Send the agency alert digests now (on-demand)",
    description=(
        "Emails each active agency its NEW relevant alerts since its last digest. "
        "`force=true` sends even with no new alerts (demo/test)."
    ),
)
async def send_now(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
    force: bool = False,
) -> SuccessResponse[SendResultData]:
    results = await send_agency_digests(session, force=force)
    return SuccessResponse(data=SendResultData(results=results), meta=_meta())
