"""POST /api/v1/cropguard/prices/bulk — Module 04 bulk price CSV ingest.

Sister to routers/cropguard_prices.py (read-only price series +
correlation matrix). Split out so the read router stays under the 300-line
cap (CLAUDE.md §4.3) and so the upload-path transaction semantics — one
DB transaction per upload — are visually obvious.

Contract:
  - multipart/form-data:
      file:   CSV (text/csv or application/csv, ≤5 MB, ≤20_000 rows)
      source: audit tag stamped on every row inserted. Convention:
              nbs_fpw_v1       — NBS Food Price Watch (Nigeria, monthly)
              wfp_hdx_v1       — WFP HDX food prices feed
              faostat_v1       — FAO Food Price Database
              amis_v1          — AMIS (Agricultural Market Info System)
              manual_admin_v1  — operator-entered fixture
  - No tenant header required: crop_prices is a public/cross-tenant
    table per migration 0015. Anyone with admin can upload.
  - UPSERTs on (crop, region, observed_at, source) per the existing
    unique constraint. Re-uploading the same NBS bulletin replaces
    cleanly; different sources for the same (crop, region, date) coexist
    so the dashboard can show NBS vs WFP HDX divergence as a credibility
    cross-check.
  - Returns BulkPriceUploadResult with rows_inserted/skipped split + the
    distinct crops_seen / regions_seen so the admin UI can render
    "imported 2,310 rows across 14 crops × 11 regions".

Whole batch lands in one transaction: half-applied state across a
monthly bulletin would be very hard to reconcile downstream against
the correlation matrix.
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
from schemas.cropguard import BulkPriceUploadResult
from schemas.envelope import ResponseMeta, SuccessResponse
from services.crop_prices_csv import (
    CsvParseError,
    MAX_CSV_BYTES,
    ParsedPriceRow,
    parse_prices_csv,
)


router = APIRouter(prefix="/cropguard/prices", tags=["cropguard"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.post(
    "/bulk",
    response_model=SuccessResponse[BulkPriceUploadResult],
    status_code=status.HTTP_200_OK,
    summary="Admin: bulk-upload a crop-prices CSV (NBS / WFP HDX / FAOSTAT)",
)
async def upload_prices_bulk(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="CSV file ≤5 MB, ≤20,000 rows")],
    source: Annotated[
        str, Form(min_length=1, max_length=40, description=(
            "Audit-trail tag for every row in this batch. Convention: "
            "nbs_fpw_v1, wfp_hdx_v1, faostat_v1, amis_v1, manual_admin_v1."
        ))
    ],
) -> SuccessResponse[BulkPriceUploadResult]:
    blob = await file.read()
    if len(blob) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_CSV_BYTES} bytes",
        )

    try:
        outcome = parse_prices_csv(blob)
    except CsvParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    inserted = 0
    for row in outcome.valid_rows:
        await _upsert_price(session, row=row, source=source)
        inserted += 1

    await session.commit()

    crops_seen = sorted({r.crop for r in outcome.valid_rows})
    regions_seen = sorted({r.region for r in outcome.valid_rows})
    rows_received = len(outcome.valid_rows) + len(outcome.errors)

    return SuccessResponse(
        data=BulkPriceUploadResult(
            source=source,
            rows_received=rows_received,
            rows_inserted=inserted,
            rows_skipped=len(outcome.errors),
            crops_seen=crops_seen,
            regions_seen=regions_seen,
            errors=outcome.errors,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


async def _upsert_price(
    session: AsyncSession, *, row: ParsedPriceRow, source: str,
) -> None:
    """Upsert one row. Same unique key as migration 0015's constraint."""
    await session.execute(
        text(
            """
            INSERT INTO public.crop_prices (
                crop, region, observed_at, price_ngn_per_kg, source
            ) VALUES (
                :crop, :region, :observed_at, :price, :source
            )
            ON CONFLICT (crop, region, observed_at, source) DO UPDATE
              SET price_ngn_per_kg = EXCLUDED.price_ngn_per_kg
            """
        ),
        {
            "crop": row.crop,
            "region": row.region,
            "observed_at": row.observed_at,
            "price": row.price_ngn_per_kg,
            "source": source,
        },
    )
