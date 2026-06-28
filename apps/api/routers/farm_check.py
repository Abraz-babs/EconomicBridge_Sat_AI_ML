"""CropGuard Farm Check records — save + recall satellite field observations.

POST /api/v1/cropguard/farm-checks   — persist one Farm Check result.
GET  /api/v1/cropguard/farm-checks   — list recent saved checks (newest first).

The satellite reading itself is computed by the ingestion service
(apps/ingestion/sources/farm_check.py); this router only records what came back,
tagged with the coordinate, crop and LGA, into `tenant_<id>.farm_checks`
(migration 0030). The X-Tenant-Id header (the state) selects the schema —
get_session sets search_path so the bare `farm_checks` table resolves.

Companion to cropguard.py (leaf-photo predictions): both CropGuard tiers keep a
recallable, place-tagged history.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.farm_check import (
    FarmCheckRecordListData,
    FarmCheckRecordRow,
    FarmCheckSaveData,
    FarmCheckSaveRequest,
    FarmPassPoint,
    FarmStress,
    FarmTrendPoint,
)


router = APIRouter(prefix="/cropguard", tags=["cropguard"])


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


def _as_date(value: str | None) -> date | None:
    """Parse an ISO 'YYYY-MM-DD' tag into a date; tolerate anything odd."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# ─── POST /farm-checks (save) ─────────────────────────────────────────────


@router.post(
    "/farm-checks",
    response_model=SuccessResponse[FarmCheckSaveData],
    status_code=status.HTTP_201_CREATED,
    summary="Save a Farm Check result as a recallable field record",
)
async def save_farm_check(
    body: FarmCheckSaveRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[FarmCheckSaveData]:
    tenant_id = _require_tenant(request)
    record_id = uuid4()

    # Full result for faithful recall — the headline columns cover filtering;
    # detail keeps the trend, every usable pass, and the provenance note.
    detail = {
        "trend": [p.model_dump() for p in body.trend],
        "passes": [p.model_dump() for p in body.passes],
        "stress": body.stress.model_dump() if body.stress else None,
        "note": body.note,
        "source": body.source,
    }

    await session.execute(
        text(
            """
            INSERT INTO farm_checks (
                id, tenant_id,
                location, lat, lon, crop, lga,
                ndvi, ndvi_date, health, verdict,
                sar_db, sar_date,
                stress_level, stress_z, stress_message,
                sample_count, area_ha, resolution_m,
                detail, source, note, trace_id, created_at
            ) VALUES (
                :id, :tenant_id,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :lat, :lon, :crop, :lga,
                :ndvi, :ndvi_date, :health, :verdict,
                :sar_db, :sar_date,
                :stress_level, :stress_z, :stress_message,
                :sample_count, :area_ha, :resolution_m,
                CAST(:detail AS JSONB), :source, :note, :trace_id, :created_at
            )
            """
        ),
        {
            "id": record_id,
            "tenant_id": tenant_id,
            "lat": body.lat,
            "lon": body.lon,
            "crop": body.crop.strip(),
            "lga": (body.lga or None),
            "ndvi": body.ndvi,
            "ndvi_date": _as_date(body.ndvi_date),
            "health": body.health,
            "verdict": body.verdict,
            "sar_db": body.sar_db,
            "sar_date": _as_date(body.sar_date),
            "stress_level": body.stress.level if body.stress else None,
            "stress_z": body.stress.z if body.stress else None,
            "stress_message": body.stress.message if body.stress else None,
            "sample_count": body.sample_count,
            "area_ha": body.area_ha,
            "resolution_m": body.resolution_m,
            "detail": json.dumps(detail),
            "source": body.source,
            "note": body.note or None,
            "trace_id": _trace_id(request),
            "created_at": datetime.now(timezone.utc),
        },
    )

    return SuccessResponse(
        data=FarmCheckSaveData(record_id=record_id, saved=True),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


# ─── GET /farm-checks (recall) ────────────────────────────────────────────


@router.get(
    "/farm-checks",
    response_model=SuccessResponse[FarmCheckRecordListData],
    summary="List recent saved Farm Check records for the tenant",
)
async def list_farm_checks(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows (default 20).")
    ] = 20,
) -> SuccessResponse[FarmCheckRecordListData]:
    _require_tenant(request)

    result = await session.execute(
        text(
            """
            SELECT id, tenant_id, lat, lon, crop, lga,
                   ndvi, ndvi_date, health, verdict,
                   sar_db, sar_date,
                   stress_level, stress_z, stress_message,
                   sample_count, area_ha, resolution_m,
                   detail, source, note, created_at
              FROM farm_checks
             ORDER BY created_at DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    records = [_row_to_record(dict(r)) for r in rows]

    return SuccessResponse(
        data=FarmCheckRecordListData(records=records),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )


def _iso_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def _row_to_record(row: dict) -> FarmCheckRecordRow:
    """Map a raw `farm_checks` mapping back to its Pydantic shape, rebuilding
    the trend/passes/stress from the `detail` JSONB so recall is faithful."""
    detail = row.get("detail") or {}
    stress_d = detail.get("stress")
    return FarmCheckRecordRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        crop=row["crop"],
        lga=row.get("lga"),
        ndvi=(float(row["ndvi"]) if row.get("ndvi") is not None else None),
        ndvi_date=_iso_date(row.get("ndvi_date")),
        health=row["health"],
        verdict=row.get("verdict") or "",
        sar_db=(float(row["sar_db"]) if row.get("sar_db") is not None else None),
        sar_date=_iso_date(row.get("sar_date")),
        stress=(
            FarmStress(
                level=stress_d.get("level", "unknown"),
                z=stress_d.get("z"),
                message=stress_d.get("message", ""),
            )
            if isinstance(stress_d, dict)
            else None
        ),
        trend=[FarmTrendPoint(**p) for p in detail.get("trend", [])],
        passes=[FarmPassPoint(**p) for p in detail.get("passes", [])],
        sample_count=int(row.get("sample_count") or 0),
        area_ha=float(row.get("area_ha") or 0.0),
        resolution_m=int(row.get("resolution_m") or 11),
        source=row.get("source") or "copernicus_sentinel_v1",
        note=row.get("note"),
        created_at=row["created_at"],
    )
