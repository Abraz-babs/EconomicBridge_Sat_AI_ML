"""Subscriber CRUD endpoints.

Tenant scoping is via the `X-Tenant-Id` header (same convention as the API).
The router validates the header against the pilot allowlist and pins the
session's search_path before reading/writing `tenant_<id>.alert_subscribers`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id, set_tenant_schema
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.notify import (
    SubscriberCreate,
    SubscriberListData,
    SubscriberResponse,
)

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _require_tenant(request: Request) -> str:
    tenant = (request.headers.get("X-Tenant-Id") or "").strip().lower()
    if not is_valid_tenant_id(tenant):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if tenant else status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or missing tenant: {tenant!r}",
        )
    return tenant


@router.get("", response_model=SuccessResponse[SubscriberListData])
async def list_subscribers(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    include_inactive: bool = False,
) -> SuccessResponse[SubscriberListData]:
    tenant_id = _require_tenant(request)
    await set_tenant_schema(session, tenant_id)

    sql = (
        "SELECT id, tenant_id, full_name, phone_e164, language, lga, zone_name, "
        "       severity_threshold, alert_types, channel, is_active, "
        "       opted_in_at, opted_out_at "
        "FROM alert_subscribers"
    )
    if not include_inactive:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY opted_in_at DESC LIMIT 500"

    rows = (await session.execute(text(sql))).mappings().all()
    subscribers = [
        SubscriberResponse(
            id=r["id"],
            tenant_id=r["tenant_id"],
            full_name=r["full_name"],
            phone_e164=r["phone_e164"],
            language=r["language"],
            lga=r["lga"],
            zone_name=r["zone_name"],
            severity_threshold=r["severity_threshold"],
            alert_types=list(r["alert_types"]) if r["alert_types"] else None,
            channel=r["channel"],
            is_active=r["is_active"],
            opted_in_at=r["opted_in_at"],
            opted_out_at=r["opted_out_at"],
        )
        for r in rows
    ]

    return SuccessResponse(
        data=SubscriberListData(subscribers=subscribers),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


@router.post(
    "",
    response_model=SuccessResponse[SubscriberResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_subscriber(
    body: SubscriberCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[SubscriberResponse]:
    tenant_id = _require_tenant(request)
    await set_tenant_schema(session, tenant_id)

    sub_id = uuid4()
    try:
        await session.execute(
            text(
                """
                INSERT INTO alert_subscribers (
                    id, tenant_id, full_name, phone_e164, language,
                    lga, zone_name, severity_threshold, alert_types, channel
                ) VALUES (
                    :id, :tenant_id, :full_name, :phone_e164, :language,
                    :lga, :zone_name, :severity_threshold,
                    CAST(:alert_types AS TEXT[]),
                    :channel
                )
                """
            ),
            {
                "id": sub_id,
                "tenant_id": tenant_id,
                "full_name": body.full_name,
                "phone_e164": body.phone_e164,
                "language": body.language.value,
                "lga": body.lga,
                "zone_name": body.zone_name,
                "severity_threshold": body.severity_threshold.value,
                "alert_types": (
                    [t.value for t in body.alert_types] if body.alert_types else None
                ),
                "channel": body.channel.value,
            },
        )
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Subscriber already exists for this (phone_e164, lga) — "
                "the unique constraint prevents duplicates"
            ),
        ) from exc

    row = (await session.execute(
        text(
            "SELECT id, tenant_id, full_name, phone_e164, language, lga, zone_name, "
            "       severity_threshold, alert_types, channel, is_active, "
            "       opted_in_at, opted_out_at "
            "FROM alert_subscribers WHERE id = :id"
        ),
        {"id": sub_id},
    )).mappings().one()

    return SuccessResponse(
        data=SubscriberResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            full_name=row["full_name"],
            phone_e164=row["phone_e164"],
            language=row["language"],
            lga=row["lga"],
            zone_name=row["zone_name"],
            severity_threshold=row["severity_threshold"],
            alert_types=list(row["alert_types"]) if row["alert_types"] else None,
            channel=row["channel"],
            is_active=row["is_active"],
            opted_in_at=row["opted_in_at"],
            opted_out_at=row["opted_out_at"],
        ),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )
