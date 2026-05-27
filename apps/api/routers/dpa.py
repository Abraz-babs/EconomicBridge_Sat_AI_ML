"""DPA + Data Subject Request endpoints.

POST    /api/v1/dpa/agreements                     register a new DPA
GET     /api/v1/dpa/agreements                     list DPAs (with filters)
GET     /api/v1/dpa/agreements/{id}                fetch one DPA
PATCH   /api/v1/dpa/agreements/{id}                update status / fields

POST    /api/v1/dpa/data-subject-requests          submit a DSR (open to subjects)
GET     /api/v1/dpa/data-subject-requests          list DSRs (operator view)
PATCH   /api/v1/dpa/data-subject-requests/{id}     handler updates a DSR

These endpoints live in `public` (cross-tenant) so the operator/admin can
register agreements scoping orgs to tenants without first being scoped to
a tenant. They do NOT require X-Tenant-Id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from dependencies import require_signed_dpa
from models.dpa import DataProcessingAgreement, DataSubjectRequest
from schemas.dpa import (
    AgreementStatus,
    AgreementType,
    DpaAgreementCreate,
    DpaAgreementListData,
    DpaAgreementPatch,
    DpaAgreementResponse,
    DsrCreate,
    DsrListData,
    DsrPatch,
    DsrRequestType,
    DsrResponse,
    DsrStatus,
)
from schemas.envelope import Pagination, ResponseMeta, SuccessResponse

router = APIRouter(prefix="/dpa", tags=["dpa"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _meta(request: Request, pagination: Pagination | None = None) -> ResponseMeta:
    return ResponseMeta(
        tenant_id=None,
        trace_id=_trace_id(request),
        timestamp=datetime.now(timezone.utc),
        pagination=pagination,
    )


# ─── DPA agreements ─────────────────────────────────────────────────────────


@router.post(
    "/agreements",
    response_model=SuccessResponse[DpaAgreementResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Data Processing Agreement",
)
async def create_agreement(
    request: Request,
    body: DpaAgreementCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[DpaAgreementResponse]:
    row = DataProcessingAgreement(
        organisation_id=body.organisation_id,
        tenant_id=body.tenant_id,
        agreement_type=body.agreement_type.value,
        signatory_name=body.signatory_name,
        signatory_email=body.signatory_email,
        expires_at=body.expires_at,
        scope=body.scope,
        document_url=body.document_url,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return SuccessResponse(
        data=DpaAgreementResponse.model_validate(row),
        meta=_meta(request),
    )


@router.get(
    "/agreements",
    response_model=SuccessResponse[DpaAgreementListData],
    summary="List DPAs",
)
async def list_agreements(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    organisation_id: Annotated[UUID | None, Query(description="Filter by org.")] = None,
    tenant_id: Annotated[str | None, Query(description="Filter by tenant slug.")] = None,
    status_: Annotated[
        list[AgreementStatus] | None, Query(alias="status", description="Filter by status.")
    ] = None,
    agreement_type: Annotated[
        list[AgreementType] | None, Query(description="Filter by agreement_type.")
    ] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SuccessResponse[DpaAgreementListData]:
    stmt = select(DataProcessingAgreement)
    if organisation_id is not None:
        stmt = stmt.where(DataProcessingAgreement.organisation_id == organisation_id)
    if tenant_id is not None:
        stmt = stmt.where(DataProcessingAgreement.tenant_id == tenant_id)
    if status_:
        stmt = stmt.where(DataProcessingAgreement.status.in_([s.value for s in status_]))
    if agreement_type:
        stmt = stmt.where(
            DataProcessingAgreement.agreement_type.in_([a.value for a in agreement_type])
        )
    total_stmt = stmt.with_only_columns(DataProcessingAgreement.id)
    total = len((await session.execute(total_stmt)).all())
    rows = (
        (
            await session.execute(
                stmt.order_by(DataProcessingAgreement.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=DpaAgreementListData(
            agreements=[DpaAgreementResponse.model_validate(r) for r in rows]
        ),
        meta=_meta(request, Pagination(page=page, per_page=per_page, total=total)),
    )


@router.get(
    "/agreements/{agreement_id}",
    response_model=SuccessResponse[DpaAgreementResponse],
    summary="Fetch one DPA",
)
async def get_agreement(
    request: Request,
    agreement_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[DpaAgreementResponse]:
    row = await session.get(DataProcessingAgreement, agreement_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"DPA {agreement_id} not found")
    return SuccessResponse(
        data=DpaAgreementResponse.model_validate(row), meta=_meta(request),
    )


@router.patch(
    "/agreements/{agreement_id}",
    response_model=SuccessResponse[DpaAgreementResponse],
    summary="Update a DPA's status / fields",
)
async def patch_agreement(
    request: Request,
    agreement_id: UUID,
    body: DpaAgreementPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[DpaAgreementResponse]:
    row = await session.get(DataProcessingAgreement, agreement_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"DPA {agreement_id} not found")
    if body.status is not None:
        row.status = body.status.value
        # When status flips to signed and signed_at is unset, stamp it now.
        if body.status == AgreementStatus.SIGNED and row.signed_at is None and body.signed_at is None:
            row.signed_at = datetime.now(timezone.utc)
    if body.signatory_name is not None:
        row.signatory_name = body.signatory_name
    if body.signatory_email is not None:
        row.signatory_email = body.signatory_email
    if body.signed_at is not None:
        row.signed_at = body.signed_at
    if body.expires_at is not None:
        row.expires_at = body.expires_at
    if body.scope is not None:
        row.scope = body.scope
    if body.document_url is not None:
        row.document_url = body.document_url
    await session.flush()
    await session.refresh(row)
    return SuccessResponse(
        data=DpaAgreementResponse.model_validate(row), meta=_meta(request),
    )


# ─── Data Subject Requests ─────────────────────────────────────────────────


@router.post(
    "/data-subject-requests",
    response_model=SuccessResponse[DsrResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Submit an NDPA / GDPR data-subject right exercise",
)
async def create_dsr(
    request: Request,
    body: DsrCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[DsrResponse]:
    if body.subject_phone_e164 is None and body.subject_email is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of subject_phone_e164 or subject_email is required",
        )
    row = DataSubjectRequest(
        tenant_id=body.tenant_id,
        subject_phone_e164=body.subject_phone_e164,
        subject_email=body.subject_email,
        subject_full_name=body.subject_full_name,
        request_type=body.request_type.value,
        requester_notes=body.requester_notes,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return SuccessResponse(data=DsrResponse.model_validate(row), meta=_meta(request))


@router.get(
    "/data-subject-requests",
    response_model=SuccessResponse[DsrListData],
    summary="List data-subject requests",
    description=(
        "**PII gate (Slice 14):** requires `X-Tenant-Id` and "
        "`X-Organisation-Id` headers. The calling organisation must hold "
        "a signed, unexpired Data Processing Agreement for the tenant. "
        "Returns 403 `DPA_REQUIRED` otherwise."
    ),
    dependencies=[Depends(require_signed_dpa)],
)
async def list_dsr(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_: Annotated[
        list[DsrStatus] | None, Query(alias="status", description="Filter by status.")
    ] = None,
    request_type: Annotated[
        list[DsrRequestType] | None, Query(description="Filter by request type.")
    ] = None,
    tenant_id: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SuccessResponse[DsrListData]:
    stmt = select(DataSubjectRequest)
    if status_:
        stmt = stmt.where(DataSubjectRequest.status.in_([s.value for s in status_]))
    if request_type:
        stmt = stmt.where(
            DataSubjectRequest.request_type.in_([t.value for t in request_type])
        )
    if tenant_id is not None:
        stmt = stmt.where(DataSubjectRequest.tenant_id == tenant_id)
    total_stmt = stmt.with_only_columns(DataSubjectRequest.id)
    total = len((await session.execute(total_stmt)).all())
    rows = (
        (
            await session.execute(
                stmt.order_by(DataSubjectRequest.received_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=DsrListData(requests=[DsrResponse.model_validate(r) for r in rows]),
        meta=_meta(request, Pagination(page=page, per_page=per_page, total=total)),
    )


@router.patch(
    "/data-subject-requests/{dsr_id}",
    response_model=SuccessResponse[DsrResponse],
    summary="Update a DSR's handler status / notes",
    description=(
        "**PII gate (Slice 14):** requires `X-Tenant-Id` and "
        "`X-Organisation-Id` matching a signed DPA. Same enforcement as "
        "the list endpoint."
    ),
    dependencies=[Depends(require_signed_dpa)],
)
async def patch_dsr(
    request: Request,
    dsr_id: UUID,
    body: DsrPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[DsrResponse]:
    row = await session.get(DataSubjectRequest, dsr_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"DSR {dsr_id} not found")
    if body.status is not None:
        row.status = body.status.value
        if body.status == DsrStatus.FULFILLED and row.fulfilled_at is None and body.fulfilled_at is None:
            row.fulfilled_at = datetime.now(timezone.utc)
    if body.handler_notes is not None:
        row.handler_notes = body.handler_notes
    if body.fulfilled_at is not None:
        row.fulfilled_at = body.fulfilled_at
    await session.flush()
    await session.refresh(row)
    return SuccessResponse(data=DsrResponse.model_validate(row), meta=_meta(request))
