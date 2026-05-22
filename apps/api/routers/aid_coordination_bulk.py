"""POST /api/v1/aid_coordination/coverage/bulk — Module 02 bulk CSV ingest.

Sister to routers/aid_coordination.py (which handles the single-row admin
POST and the aggregate GET). Split out so the file stays under the 300-line
cap (CLAUDE.md §4.3) and so the bulk path's transaction semantics — one
DB transaction per upload — are visually obvious.

Contract:
  - multipart/form-data with two fields:
      file:   the CSV (text/csv or application/csv, ≤5 MB, ≤5000 rows)
      source: the audit-trail string written into aid_coverage.source
              (e.g. 'wfp_scope_v1', 'unhcr_progres_v1', 'nema_manual_v1')
  - X-Tenant-Id header required.
  - Upserts on (agency_slug, lga, source) per the existing single-row
    contract — same conflict behaviour. Unknown agency_slugs are skipped
    (per-row error reported), they do NOT abort the batch.
  - Returns BulkCoverageUploadResult with the rows_inserted/skipped split
    so the admin UI can show a clean "added 47, skipped 3" summary.

The whole batch lands in one transaction: either every valid row commits,
or nothing does. Partner-org pipelines retry the same file repeatedly —
half-applied state would be very hard to reconcile.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.aid_coordination import (
    BulkCoverageRowError,
    BulkCoverageUploadResult,
)
from schemas.envelope import ResponseMeta, SuccessResponse
from services.aid_coverage_csv import (
    CsvParseError,
    MAX_CSV_BYTES,
    ParsedRow,
    parse_csv,
)


router = APIRouter(prefix="/aid_coordination", tags=["aid-coordination"])


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


@router.post(
    "/coverage/bulk",
    response_model=SuccessResponse[BulkCoverageUploadResult],
    status_code=status.HTTP_200_OK,
    summary="Admin: bulk-upload an aid coverage CSV (WFP / UNHCR / NEMA)",
)
async def upload_coverage_bulk(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="CSV file ≤5 MB, ≤5000 rows")],
    source: Annotated[
        str, Form(min_length=1, max_length=40, description=(
            "Audit-trail tag for every row in this batch. Convention: "
            "wfp_scope_v1, unhcr_progres_v1, nema_manual_v1."
        ))
    ],
) -> SuccessResponse[BulkCoverageUploadResult]:
    tenant_id = _require_tenant(request)
    blob = await file.read()

    if len(blob) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_CSV_BYTES} bytes",
        )

    try:
        outcome = parse_csv(blob)
    except CsvParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Pre-fetch the agency registry so we can validate every slug in
    # a single query rather than N+1 round-trips.
    agency_result = await session.execute(
        text("SELECT slug FROM public.aid_agencies"),
    )
    known_slugs: set[str] = {row["slug"] for row in agency_result.mappings().all()}

    errors: list[BulkCoverageRowError] = list(outcome.errors)
    inserted = 0
    rows_received = len(outcome.valid_rows) + len(outcome.errors)

    for row in outcome.valid_rows:
        if row.agency_slug not in known_slugs:
            errors.append(BulkCoverageRowError(
                line_number=row.line_number,
                raw_row={
                    "agency_slug": row.agency_slug,
                    "lga": row.lga,
                    "beneficiaries_served": str(row.beneficiaries_served),
                    "last_active_at": (
                        row.last_active_at.isoformat() if row.last_active_at else ""
                    ),
                },
                error=(
                    f"unknown agency_slug {row.agency_slug!r}; "
                    "register it in public.aid_agencies first"
                ),
            ))
            continue
        await _upsert_row(
            session, tenant_id=tenant_id, row=row, source=source,
        )
        inserted += 1

    await session.commit()

    return SuccessResponse(
        data=BulkCoverageUploadResult(
            tenant_id=tenant_id,
            source=source,
            rows_received=rows_received,
            rows_inserted=inserted,
            rows_skipped=len(errors),
            errors=errors,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


async def _upsert_row(
    session: AsyncSession,
    *,
    tenant_id: str,
    row: ParsedRow,
    source: str,
) -> None:
    """Same UPSERT as the single-row endpoint — keep both code paths
    aligned so the conflict semantics don't drift."""
    await session.execute(
        text(
            """
            INSERT INTO aid_coverage (
                tenant_id, agency_slug, lga,
                beneficiaries_served, last_active_at, source
            ) VALUES (
                :tenant_id, :agency_slug, :lga,
                :beneficiaries, :last_active, :source
            )
            ON CONFLICT (agency_slug, lga, source) DO UPDATE
              SET beneficiaries_served = EXCLUDED.beneficiaries_served,
                  last_active_at = EXCLUDED.last_active_at,
                  updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "agency_slug": row.agency_slug,
            "lga": row.lga,
            "beneficiaries": row.beneficiaries_served,
            "last_active": row.last_active_at,
            "source": source,
        },
    )
