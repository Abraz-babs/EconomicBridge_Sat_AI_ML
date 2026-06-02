"""POST /api/v1/subscribers/bulk — bulk farmer-contact CSV import.

Loads a partner-agency contact list (per state/tenant) into
`tenant_<id>.alert_subscribers`. Upserts on the table's UNIQUE (phone_e164,
lga) so re-uploads refresh language/threshold instead of duplicating.

Contract:
  - multipart/form-data, field `file`: CSV (≤5 MB) with header
        phone_e164,lga,language,severity_threshold  (+ optional full_name)
  - X-Tenant-Id header required (selects the state/country).
  - One transaction per upload; per-row errors are reported, not fatal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id, set_tenant_schema
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.notify import (
    BulkSubscriberRowError,
    BulkSubscriberUploadResult,
)
from services.subscriber_csv import (
    CsvParseError,
    MAX_CSV_BYTES,
    parse_subscriber_csv,
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


@router.post(
    "/bulk",
    response_model=SuccessResponse[BulkSubscriberUploadResult],
    status_code=status.HTTP_200_OK,
    summary="Admin: bulk-import farmer contacts (CSV) for a state/tenant",
)
async def upload_subscribers_bulk(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="CSV ≤5 MB")],
) -> SuccessResponse[BulkSubscriberUploadResult]:
    tenant_id = _require_tenant(request)
    blob = await file.read()
    if len(blob) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_CSV_BYTES} bytes",
        )
    try:
        outcome = parse_subscriber_csv(blob)
    except CsvParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await set_tenant_schema(session, tenant_id)

    inserted = 0
    updated = 0
    errors: list[BulkSubscriberRowError] = list(outcome.errors)
    for row in outcome.valid_rows:
        # `xmax = 0` on the returned row means a fresh INSERT; otherwise the
        # ON CONFLICT path updated an existing (phone, lga) subscriber.
        res = await session.execute(
            text(
                """
                INSERT INTO alert_subscribers (
                    tenant_id, full_name, phone_e164, language,
                    lga, severity_threshold, channel, is_active
                ) VALUES (
                    :tenant_id, :full_name, :phone, :language,
                    :lga, :threshold, 'sms', TRUE
                )
                ON CONFLICT (phone_e164, lga) DO UPDATE
                  SET language = EXCLUDED.language,
                      severity_threshold = EXCLUDED.severity_threshold,
                      full_name = COALESCE(EXCLUDED.full_name, alert_subscribers.full_name),
                      is_active = TRUE,
                      updated_at = NOW()
                RETURNING (xmax = 0) AS was_insert
                """
            ),
            {
                "tenant_id": tenant_id,
                "full_name": row.full_name,
                "phone": row.phone_e164,
                "language": row.language,
                "lga": row.lga,
                "threshold": row.severity_threshold,
            },
        )
        was_insert = res.scalar()
        if was_insert:
            inserted += 1
        else:
            updated += 1

    await session.commit()

    return SuccessResponse(
        data=BulkSubscriberUploadResult(
            tenant_id=tenant_id,
            rows_received=len(outcome.valid_rows) + len(outcome.errors),
            rows_inserted=inserted,
            rows_updated=updated,
            rows_skipped=len(errors),
            errors=errors,
        ),
        meta=ResponseMeta(
            tenant_id=tenant_id,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )
