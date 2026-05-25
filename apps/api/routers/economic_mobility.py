"""GET /api/v1/economic_mobility/indicators — Module 06 (Mobility Compass).

Read-only consumer of `tenant_<id>.mobility_indicators` (migration 0022).
Returns the full per-LGA list plus aggregate rollups (median COL,
median income, cheapest/most-expensive LGA, best opportunity / capacity)
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
from schemas.economic_mobility import (
    LonLat,
    MobilityIndicatorRow,
    MobilityStatsData,
)
from schemas.envelope import ResponseMeta, SuccessResponse


router = APIRouter(prefix="/economic_mobility", tags=["economic-mobility"])


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


def _col_band(col: float) -> str:
    """Map cost-of-living index to a descriptive band the dashboard uses
    to colour the LGA points (cheaper → green, expensive → red)."""
    if col >= 140:
        return "premium"
    if col >= 110:
        return "above_avg"
    if col >= 85:
        return "near_avg"
    return "below_avg"


@router.get(
    "/indicators",
    response_model=SuccessResponse[MobilityStatsData],
    summary="Per-LGA mobility indicators + aggregate stats for a tenant",
)
async def list_indicators(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=200, description="Max LGAs returned.")
    ] = 100,
) -> SuccessResponse[MobilityStatsData]:
    tenant_id = _require_tenant(request)

    result = await session.execute(
        text(
            """
            SELECT id, tenant_id, lga,
                   ST_X(location) AS lon, ST_Y(location) AS lat,
                   cost_of_living_index, avg_household_income_ngn,
                   income_opportunity_score, displacement_capacity_index,
                   population, observed_at, source, created_at, updated_at
              FROM mobility_indicators
             ORDER BY cost_of_living_index DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    indicators = [
        MobilityIndicatorRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            cost_of_living_index=float(r["cost_of_living_index"]),
            cost_of_living_band=_col_band(float(r["cost_of_living_index"])),
            avg_household_income_ngn=int(r["avg_household_income_ngn"]),
            income_opportunity_score=float(r["income_opportunity_score"]),
            displacement_capacity_index=float(r["displacement_capacity_index"]),
            population=int(r["population"]),
            observed_at=r["observed_at"],
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    if indicators:
        sorted_col = sorted(indicators, key=lambda i: i.cost_of_living_index)
        sorted_income = sorted(indicators, key=lambda i: i.avg_household_income_ngn)
        cheapest = sorted_col[0].lga
        most_expensive = sorted_col[-1].lga
        median_col = sorted_col[len(sorted_col) // 2].cost_of_living_index
        median_income = sorted_income[len(sorted_income) // 2].avg_household_income_ngn
        best_opp = max(indicators, key=lambda i: i.income_opportunity_score).lga
        best_cap = max(indicators, key=lambda i: i.displacement_capacity_index).lga
    else:
        cheapest = most_expensive = best_opp = best_cap = None
        median_col = 0.0
        median_income = 0

    sources = sorted({i.source for i in indicators})

    return SuccessResponse(
        data=MobilityStatsData(
            tenant_id=tenant_id,
            total_lgas=len(indicators),
            median_cost_of_living=median_col,
            median_household_income_ngn=median_income,
            cheapest_lga=cheapest,
            most_expensive_lga=most_expensive,
            best_opportunity_lga=best_opp,
            best_capacity_lga=best_cap,
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
