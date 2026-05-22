"""POST /api/v1/cropguard/ndvi/scan   — run 14-day anomaly detector.
GET  /api/v1/cropguard/ndvi/anomalies — recent persisted anomaly events.

Both consume `tenant_<id>.ndvi_anomalies` (migration 0017). Scan
generates the synthetic NDVI series, runs the detector, returns the
full 90-day series + detection metrics, and (when persist=True) writes
one row. List endpoint is the audit-trail viewer.

The synthetic series will be replaced by real Sentinel-2 ingestion in
a follow-up slice; the detector + endpoint contract stay unchanged.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.cropguard import (
    NdviAnomalyListData,
    NdviAnomalyRow,
    NdviSamplePoint,
    NdviScanData,
    NdviScanRequest,
)
from schemas.envelope import ResponseMeta, SuccessResponse
from services import ndvi_anomaly as ndvi_service
from services.live_satellite import LiveDataMissingError, load_ndvi_series
from services.tenants import tenant_schema_name


router = APIRouter(prefix="/cropguard/ndvi", tags=["cropguard"])


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


def _to_utc_dt(d) -> datetime:
    """date → tz-aware UTC datetime at midnight."""
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time(0, 0, tzinfo=timezone.utc))


# ─── POST /scan ───────────────────────────────────────────────────────────


@router.post(
    "/scan",
    response_model=SuccessResponse[NdviScanData],
    summary="Run the 14-day NDVI anomaly detector for the tenant ROI",
)
async def scan_ndvi_anomaly(
    body: NdviScanRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[NdviScanData]:
    tenant_id = _require_tenant(request)

    if body.data_source == "live":
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(tenant_id)}, public"),
        )
        try:
            series = await load_ndvi_series(session)
        except LiveDataMissingError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
    else:
        series = ndvi_service.synthetic_series(
            tenant_id, inject_anomaly=body.demo_inject_anomaly,
        )
    # Real S2 has ~5-day repeat per state ROI — pass sparse-data window
    # sizes so the detector works on actual acquisition counts (~3 recent,
    # ~12 baseline gives the same 14d / 60d coverage as the synthetic path).
    detect_kwargs = (
        {"recent_n": 3, "baseline_n": 12} if body.data_source == "live" else {}
    )
    try:
        result = ndvi_service.detect_anomaly(
            tenant_id=tenant_id, series=series, crop=body.crop, **detect_kwargs,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    anomaly_id: UUID | None = None
    persisted = False
    if body.persist:
        anomaly_id = await _persist_anomaly(
            session, tenant_id=tenant_id, result=result,
            trace_id=_trace_id(request),
        )
        persisted = anomaly_id is not None

    series_points = [
        NdviSamplePoint(observed_at=_to_utc_dt(s.observed_at), ndvi=s.ndvi)
        for s in result.series
    ]

    return SuccessResponse(
        data=NdviScanData(
            anomaly_id=anomaly_id,
            tenant_id=tenant_id,
            detector_name=result.detector_name,
            detector_version=result.detector_version,
            window_start=_to_utc_dt(result.window_start),
            window_end=_to_utc_dt(result.window_end),
            days_early_warning=result.days_early_warning,
            ndvi_recent_mean=result.ndvi_recent_mean,
            ndvi_baseline_mean=result.ndvi_baseline_mean,
            ndvi_baseline_std=result.ndvi_baseline_std,
            z_score=result.z_score,
            disease_probability=result.disease_probability,
            anomaly=result.anomaly,
            confidence_band=result.confidence_band,
            series=series_points,
            crop=result.crop,
            persisted=persisted,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


# ─── GET /anomalies ───────────────────────────────────────────────────────


@router.get(
    "/anomalies",
    response_model=SuccessResponse[NdviAnomalyListData],
    summary="List recent NDVI anomaly events for the tenant",
)
async def list_ndvi_anomalies(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows (default 20).")
    ] = 20,
    anomalies_only: Annotated[
        bool, Query(description="Filter to anomaly=true rows only.")
    ] = False,
) -> SuccessResponse[NdviAnomalyListData]:
    _require_tenant(request)

    where_clause = "WHERE anomaly = TRUE" if anomalies_only else ""
    result = await session.execute(
        text(
            f"""
            SELECT id, tenant_id, detector_name, detector_version,
                   window_start, window_end,
                   ndvi_recent_mean, ndvi_baseline_mean, ndvi_baseline_std,
                   z_score, disease_probability, anomaly, confidence_band,
                   crop, created_at
              FROM ndvi_anomalies
              {where_clause}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    anomalies = [
        NdviAnomalyRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            detector_name=r["detector_name"],
            detector_version=r["detector_version"],
            window_start=_to_utc_dt(r["window_start"]),
            window_end=_to_utc_dt(r["window_end"]),
            ndvi_recent_mean=float(r["ndvi_recent_mean"]),
            ndvi_baseline_mean=float(r["ndvi_baseline_mean"]),
            ndvi_baseline_std=float(r["ndvi_baseline_std"]),
            z_score=float(r["z_score"]),
            disease_probability=float(r["disease_probability"]),
            anomaly=bool(r["anomaly"]),
            confidence_band=r["confidence_band"],
            crop=r.get("crop"),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return SuccessResponse(
        data=NdviAnomalyListData(anomalies=anomalies),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


# ─── Persistence helper ───────────────────────────────────────────────────


async def _persist_anomaly(
    session: AsyncSession,
    *,
    tenant_id: str,
    result: ndvi_service.AnomalyResult,
    trace_id: UUID,
) -> UUID:
    anomaly_id = uuid4()
    from services.tenants import tenant_schema_name
    schema = tenant_schema_name(tenant_id)
    await session.execute(text(f"SET search_path TO {schema}, public"))
    await session.execute(
        text(
            """
            INSERT INTO ndvi_anomalies (
                id, tenant_id, detector_name, detector_version,
                window_start, window_end,
                ndvi_recent_mean, ndvi_baseline_mean, ndvi_baseline_std,
                z_score, disease_probability, anomaly, confidence_band,
                crop, trace_id, created_at
            ) VALUES (
                :id, :tenant_id, :detector_name, :detector_version,
                :window_start, :window_end,
                :ndvi_recent_mean, :ndvi_baseline_mean, :ndvi_baseline_std,
                :z_score, :disease_probability, :anomaly, :confidence_band,
                :crop, :trace_id, :created_at
            )
            """
        ),
        {
            "id": anomaly_id,
            "tenant_id": tenant_id,
            "detector_name": result.detector_name,
            "detector_version": result.detector_version,
            "window_start": result.window_start,
            "window_end": result.window_end,
            "ndvi_recent_mean": result.ndvi_recent_mean,
            "ndvi_baseline_mean": result.ndvi_baseline_mean,
            "ndvi_baseline_std": result.ndvi_baseline_std,
            "z_score": result.z_score,
            "disease_probability": result.disease_probability,
            "anomaly": result.anomaly,
            "confidence_band": result.confidence_band,
            "crop": result.crop,
            "trace_id": trace_id,
            "created_at": datetime.now(timezone.utc),
        },
    )
    return anomaly_id
