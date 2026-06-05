"""GET /api/v1/cropguard/prices         — time series for one crop, one region.
GET /api/v1/cropguard/prices/correlation — Pearson correlation matrix across crops.

Read-only over `public.crop_prices` (migration 0015). No tenant header
required: prices are regional/national and not tenant-isolated. The
`region` query param picks the slice — defaults to the requesting
tenant when X-Tenant-Id is set, otherwise falls back to `nigeria_national`
once that aggregation lands.

Correlation is computed on monthly log-returns (so r=1 means the two
crops moved together every month). Pure-Python implementation — for
14 crops × 24 months that's a 14×14 matrix, no need for a numpy dep.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.cropguard import (
    CropPriceCorrelationData,
    CropPricePoint,
    CropPriceSeriesData,
)
from schemas.envelope import ResponseMeta, SuccessResponse


router = APIRouter(prefix="/cropguard/prices", tags=["cropguard"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _resolve_region(request: Request, override: str | None) -> str:
    """Pick the region for this query.

    Priority:
      1. Explicit `region` query param if supplied.
      2. The tenant_id from X-Tenant-Id (middleware-validated).
      3. 400 — caller didn't tell us which slice they want.
    """
    if override:
        return override.strip().lower()
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Either supply ?region=... or set the X-Tenant-Id header so we "
            "know which regional slice you want."
        ),
    )


# ─── Time series ──────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=SuccessResponse[CropPriceSeriesData],
    summary="Monthly price history for one crop in one region",
)
async def get_price_series(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    crop: Annotated[str, Query(min_length=1, max_length=40)],
    region: Annotated[str | None, Query(max_length=60)] = None,
    months: Annotated[int, Query(ge=1, le=60)] = 24,
) -> SuccessResponse[CropPriceSeriesData]:
    target_region = _resolve_region(request, region)
    target_crop = crop.strip().lower()

    result = await session.execute(
        text(
            """
            SELECT crop, region, observed_at, price_ngn_per_kg, source
              FROM public.crop_prices
             WHERE crop = :crop AND region = :region
             ORDER BY observed_at DESC
             LIMIT :limit
            """
        ),
        {"crop": target_crop, "region": target_region, "limit": months},
    )
    rows = list(result.mappings())
    # Oldest-first for charting.
    rows.reverse()

    points = [
        CropPricePoint(
            crop=r["crop"], region=r["region"],
            observed_at=_to_dt(r["observed_at"]),
            price_ngn_per_kg=float(r["price_ngn_per_kg"]),
            source=r["source"],
        )
        for r in rows
    ]
    latest = points[-1].price_ngn_per_kg if points else None
    earliest = points[0].price_ngn_per_kg if points else None
    pct = (
        ((latest - earliest) / earliest) * 100
        if latest is not None and earliest is not None and earliest > 0
        else None
    )
    sources = sorted({p.source for p in points})

    return SuccessResponse(
        data=CropPriceSeriesData(
            crop=target_crop,
            region=target_region,
            months=months,
            points=points,
            latest_price=latest,
            earliest_price=earliest,
            pct_change=pct,
            sources=sources,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


# ─── Correlation matrix ───────────────────────────────────────────────────


@router.get(
    "/correlation",
    response_model=SuccessResponse[CropPriceCorrelationData],
    summary="Pearson correlation matrix across all crops in one region",
)
async def get_correlation_matrix(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    region: Annotated[str | None, Query(max_length=60)] = None,
    months: Annotated[int, Query(ge=3, le=60)] = 24,
) -> SuccessResponse[CropPriceCorrelationData]:
    target_region = _resolve_region(request, region)

    result = await session.execute(
        text(
            """
            SELECT crop, observed_at, price_ngn_per_kg
              FROM public.crop_prices
             WHERE region = :region
               AND observed_at >= (CURRENT_DATE - make_interval(months => :months))
             ORDER BY observed_at ASC
            """
        ),
        {"region": target_region, "months": months},
    )

    # Group rows into per-crop monthly series, aligned on observation date.
    series: dict[str, dict[str, float]] = {}
    for row in result.mappings():
        crop = row["crop"]
        ym = row["observed_at"].strftime("%Y-%m")
        series.setdefault(crop, {})[ym] = float(row["price_ngn_per_kg"])

    crops = sorted(series.keys())
    if len(crops) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Need at least 2 crops with data in region={target_region!r} "
                f"to compute correlation; got {len(crops)}."
            ),
        )

    # Build aligned log-return vectors. We use the intersection of
    # observation dates across crops to keep the math honest — any crop
    # missing a month doesn't get a synthetic fill that would bias r.
    all_ym = sorted(set.intersection(*(set(series[c].keys()) for c in crops)))
    matrix = _correlation_matrix(crops, series, all_ym)

    return SuccessResponse(
        data=CropPriceCorrelationData(
            region=target_region,
            months=months,
            crops=crops,
            matrix=matrix,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


# ─── Pure math helpers ────────────────────────────────────────────────────


def _correlation_matrix(
    crops: list[str],
    series: dict[str, dict[str, float]],
    aligned_ym: list[str],
) -> list[list[float]]:
    """Pearson correlation on monthly log-returns. r=1 means co-movement."""
    if len(aligned_ym) < 3:
        # Not enough overlap to compute log-returns; return identity.
        return [[1.0 if i == j else 0.0 for j in range(len(crops))]
                for i in range(len(crops))]

    returns: dict[str, list[float]] = {}
    for crop in crops:
        prev = series[crop][aligned_ym[0]]
        crop_returns: list[float] = []
        for ym in aligned_ym[1:]:
            curr = series[crop][ym]
            if prev <= 0 or curr <= 0:
                crop_returns.append(0.0)
            else:
                crop_returns.append(math.log(curr / prev))
            prev = curr
        returns[crop] = crop_returns

    matrix: list[list[float]] = []
    for c1 in crops:
        row: list[float] = []
        for c2 in crops:
            row.append(_pearson(returns[c1], returns[c2]))
        matrix.append(row)
    return matrix


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson r. Returns 0.0 (not NaN) for zero-variance series so the
    matrix is always JSON-safe."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var_x = sum((xs[i] - mean_x) ** 2 for i in range(n))
    var_y = sum((ys[i] - mean_y) ** 2 for i in range(n))
    denom = math.sqrt(var_x * var_y)
    if denom <= 0:
        return 0.0
    return cov / denom


def _to_dt(observed_at: object) -> datetime:
    """Coerce a SQL DATE column to a tz-aware datetime at UTC midnight."""
    if isinstance(observed_at, datetime):
        return observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    from datetime import date
    if isinstance(observed_at, date):
        return datetime(
            observed_at.year, observed_at.month, observed_at.day,
            tzinfo=timezone.utc,
        )
    raise TypeError(f"Unexpected observed_at type: {type(observed_at).__name__}")
