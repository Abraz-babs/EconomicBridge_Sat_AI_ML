"""GET /api/v1/skills/indicators — Module 07 (SkillsBridge).

Read-only consumer of `tenant_<id>.skills_indicators` (migration 0023).
Returns the full per-LGA list plus aggregate rollups (median internet
coverage, total schools/youth pop, best-connectivity / worst-gap LGA)
so the dashboard renders without doing the math client-side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.skills import (
    LonLat,
    SkillsIndicatorRow,
    SkillsStatsData,
)


router = APIRouter(prefix="/skills", tags=["skills"])


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


def _connectivity_band(internet_pct: float) -> str:
    """Map internet coverage % to a descriptive band the dashboard uses
    to colour LGA points (broadband → green, no_signal → red)."""
    if internet_pct >= 60:
        return "broadband"
    if internet_pct >= 30:
        return "basic"
    if internet_pct >= 10:
        return "limited"
    return "no_signal"


@router.get(
    "/indicators",
    response_model=SuccessResponse[SkillsStatsData],
    summary="Per-LGA education + connectivity indicators for a tenant",
)
async def list_indicators(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=200, description="Max LGAs returned.")
    ] = 100,
) -> SuccessResponse[SkillsStatsData]:
    tenant_id = _require_tenant(request)

    result = await session.execute(
        text(
            """
            SELECT id, tenant_id, lga,
                   ST_X(location) AS lon, ST_Y(location) AS lat,
                   school_count, school_density_per_10k,
                   internet_coverage_pct, mobile_coverage_pct,
                   electricity_reliability, youth_population,
                   learning_gap_index, observed_at, source,
                   created_at, updated_at
              FROM skills_indicators
             ORDER BY learning_gap_index DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    indicators = [
        SkillsIndicatorRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            school_count=int(r["school_count"]),
            school_density_per_10k=float(r["school_density_per_10k"]),
            internet_coverage_pct=float(r["internet_coverage_pct"]),
            connectivity_band=_connectivity_band(float(r["internet_coverage_pct"])),
            mobile_coverage_pct=float(r["mobile_coverage_pct"]),
            electricity_reliability=float(r["electricity_reliability"]),
            youth_population=int(r["youth_population"]),
            learning_gap_index=float(r["learning_gap_index"]),
            observed_at=r["observed_at"],
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    if indicators:
        sorted_net = sorted(indicators, key=lambda i: i.internet_coverage_pct)
        sorted_density = sorted(indicators, key=lambda i: i.school_density_per_10k)
        median_net = sorted_net[len(sorted_net) // 2].internet_coverage_pct
        median_density = sorted_density[len(sorted_density) // 2].school_density_per_10k
        best_conn = sorted_net[-1].lga
        worst_gap = max(indicators, key=lambda i: i.learning_gap_index).lga
        most_underserved = sorted_density[0].lga
        most_schools = max(indicators, key=lambda i: i.school_count).lga
        total_schools = sum(i.school_count for i in indicators)
        total_youth = sum(i.youth_population for i in indicators)
    else:
        median_net = 0.0
        median_density = 0.0
        best_conn = worst_gap = most_underserved = most_schools = None
        total_schools = 0
        total_youth = 0

    sources = sorted({i.source for i in indicators})

    return SuccessResponse(
        data=SkillsStatsData(
            tenant_id=tenant_id,
            total_lgas=len(indicators),
            median_internet_coverage_pct=median_net,
            median_school_density=median_density,
            total_schools=total_schools,
            total_youth_population=total_youth,
            best_connectivity_lga=best_conn,
            worst_gap_lga=worst_gap,
            most_underserved_lga=most_underserved,
            most_schools_lga=most_schools,
            indicators=indicators,
            sources=sources,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )
