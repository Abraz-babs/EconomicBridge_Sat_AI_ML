"""POST /api/v1/shockguard/scan   — run flood OR drought detector
GET  /api/v1/shockguard/events — recent persisted shock events

Both consume tenant_<id>.shock_events (migration 0020). Scan runs the
appropriate statistical detector from services/shock_detector.py
(synthetic series for now; real Sentinel-1 GRD / MODIS LST when those
ingestion paths land), returns the full series for the chart, and
optionally persists the event row.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.shockguard import (
    DroughtSeriesPoint,
    FloodSeriesPoint,
    LonLat,
    ShockEventListData,
    ShockEventRow,
    ShockScanData,
    ShockScanRequest,
)
from services import shock_detector
from services.live_satellite import LiveDataMissingError, load_flood_series
from services.shock_detector import to_utc_dt
from services.tenants import tenant_schema_name


router = APIRouter(prefix="/shockguard", tags=["shockguard"])


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


def _event_row(r: Mapping[str, Any]) -> ShockEventRow:
    """Map a `shock_events` row mapping to its API shape.

    `lon`/`lat` come from ST_X/ST_Y(location); both are NULL for events with
    no geometry, in which case `location` is omitted and the map synthesises
    a position.
    """
    lon, lat = r.get("lon"), r.get("lat")
    location = LonLat(lon=float(lon), lat=float(lat)) if lon is not None and lat is not None else None
    return ShockEventRow(
        id=r["id"],
        tenant_id=r["tenant_id"],
        event_type=r["event_type"],
        detector_name=r["detector_name"],
        detector_version=r["detector_version"],
        severity=r["severity"],
        confidence=float(r["confidence"]),
        confidence_band=r["confidence_band"],
        requires_human_review=bool(r["requires_human_review"]),
        projected_onset_hours=int(r["projected_onset_hours"]),
        affected_area_km2=float(r["affected_area_km2"]),
        population_at_risk=int(r["population_at_risk"]),
        lga=r.get("lga"),
        zone_name=r.get("zone_name"),
        location=location,
        metrics=r.get("metrics") or {},
        source=r["source"],
        created_at=r["created_at"],
    )


# ─── POST /scan ───────────────────────────────────────────────────────────


@router.post(
    "/scan",
    response_model=SuccessResponse[ShockScanData],
    summary="Run a flood or drought detector for the active tenant",
)
async def scan_shock(
    body: ShockScanRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ShockScanData]:
    tenant_id = _require_tenant(request)

    # Live mode pulls real Sentinel-1 SAR rows from
    # tenant_<id>.satellite_observations (drought stays synthetic for
    # now — MODIS LST ingestion is Phase B). data_source='synthetic'
    # is the default and remains the demo path.
    live_series = None
    if body.data_source == "live" and body.event_type == "flood":
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(tenant_id)}, public"),
        )
        try:
            live_series = await load_flood_series(session)
        except LiveDataMissingError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    try:
        if body.event_type == "flood":
            # Real S1 SAR has a ~6-day repeat per ROI — pass sparse-data
            # window sizes so the detector doesn't choke on point-counts
            # below the synthetic-daily defaults.
            flood_kwargs = (
                {"recent_n": 3, "baseline_n": 8} if live_series is not None else {}
            )
            detection = shock_detector.detect_flood(
                tenant_id,
                series=live_series,
                inject_flood=body.demo_inject_anomaly and live_series is None,
                **flood_kwargs,
            )
        else:
            # Drought detector remains synthetic until MODIS LST lands.
            detection = shock_detector.detect_drought(
                tenant_id, inject_drought=body.demo_inject_anomaly,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from exc

    event_id: UUID | None = None
    persisted = False
    if body.persist and detection.triggered:
        # Only persist actual triggered events. Negative scans are
        # informative but bloat the audit log if every dashboard load
        # writes "no flood today".
        event_id = await _persist_event(
            session,
            tenant_id=tenant_id, detection=detection,
            trace_id=_trace_id(request),
        )
        persisted = event_id is not None

    flood_pts = [
        FloodSeriesPoint(observed_at=to_utc_dt(p.observed_at),
                         backscatter_db=p.backscatter_db)
        for p in detection.flood_series
    ]
    drought_pts = [
        DroughtSeriesPoint(
            observed_at=to_utc_dt(p.observed_at),
            lst_anomaly_c=p.lst_anomaly_c,
            ndvi_anomaly=p.ndvi_anomaly,
            stress_index=p.stress_index,
        )
        for p in detection.drought_series
    ]

    return SuccessResponse(
        data=ShockScanData(
            event_id=event_id,
            tenant_id=tenant_id,
            event_type=detection.event_type,
            detector_name=detection.detector_name,
            detector_version=detection.detector_version,
            severity=detection.severity,
            confidence=detection.confidence,
            confidence_band=detection.confidence_band,
            requires_human_review=detection.requires_human_review,
            triggered=detection.triggered,
            projected_onset_hours=detection.projected_onset_hours,
            affected_area_km2=detection.affected_area_km2,
            population_at_risk=detection.population_at_risk,
            metrics=detection.metrics,
            flood_series=flood_pts,
            drought_series=drought_pts,
            persisted=persisted,
        ),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
        ),
    )


# ─── GET /events ──────────────────────────────────────────────────────────


@router.get(
    "/events",
    response_model=SuccessResponse[ShockEventListData],
    summary="List recent shock events (flood + drought) for the tenant",
)
async def list_events(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max rows (default 20).")
    ] = 20,
    event_type: Annotated[
        str | None, Query(description="Filter to 'flood' or 'drought'.")
    ] = None,
) -> SuccessResponse[ShockEventListData]:
    _require_tenant(request)

    where_clause = ""
    params: dict[str, object] = {"limit": limit}
    if event_type:
        if event_type not in ("flood", "drought"):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported event_type {event_type!r}",
            )
        where_clause = "WHERE event_type = :event_type"
        params["event_type"] = event_type

    result = await session.execute(
        text(
            f"""
            SELECT id, tenant_id, event_type, detector_name, detector_version,
                   severity, confidence, confidence_band, requires_human_review,
                   projected_onset_hours, affected_area_km2, population_at_risk,
                   lga, zone_name, metrics, source, created_at,
                   ST_X(location) AS lon, ST_Y(location) AS lat
              FROM shock_events
              {where_clause}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        ),
        params,
    )
    rows = result.mappings().all()

    events = [_event_row(r) for r in rows]

    return SuccessResponse(
        data=ShockEventListData(events=events),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )


# ─── Persistence helper ───────────────────────────────────────────────────


async def _persist_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    detection: shock_detector.ShockDetection,
    trace_id: UUID,
) -> UUID:
    event_id = uuid4()
    from services.tenants import tenant_schema_name
    schema = tenant_schema_name(tenant_id)
    await session.execute(text(f"SET search_path TO {schema}, public"))
    await session.execute(
        text(
            """
            INSERT INTO shock_events (
                id, tenant_id, event_type, detector_name, detector_version,
                severity, confidence, confidence_band, requires_human_review,
                projected_onset_hours, affected_area_km2, population_at_risk,
                metrics, source, trace_id, created_at
            ) VALUES (
                :id, :tenant_id, :event_type, :detector_name, :detector_version,
                :severity, :confidence, :confidence_band, :requires_human_review,
                :projected_onset_hours, :affected_area_km2, :population_at_risk,
                CAST(:metrics AS JSONB), :source, :trace_id, :created_at
            )
            """
        ),
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "event_type": detection.event_type,
            "detector_name": detection.detector_name,
            "detector_version": detection.detector_version,
            "severity": detection.severity,
            "confidence": detection.confidence,
            "confidence_band": detection.confidence_band,
            "requires_human_review": detection.requires_human_review,
            "projected_onset_hours": detection.projected_onset_hours,
            "affected_area_km2": detection.affected_area_km2,
            "population_at_risk": detection.population_at_risk,
            "metrics": json.dumps(detection.metrics),
            "source": "detector_v1",
            "trace_id": trace_id,
            "created_at": datetime.now(timezone.utc),
        },
    )
    return event_id
