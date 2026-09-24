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
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.shockguard import (
    DroughtSeriesPoint,
    FeedStatus,
    FloodSeriesPoint,
    LonLat,
    ShockEventListData,
    ShockEventRow,
    ShockScanData,
    ShockScanRequest,
    StormListData,
    StormMeasurement,
    StormRow,
)
from services import lga_geo, shock_detector
from services.auto_notify import fire_conflict_notification
from services.data_source import LIVE, NOT_SYNTHETIC, STORED_ONLY_WHEN_LIVE, may_store
from services.places import nearest_places
from services.live_satellite import LiveDataMissingError, load_flood_series
from services.shock_detector import to_utc_dt
from services.tenants import tenant_schema_name


router = APIRouter(prefix="/shockguard", tags=["shockguard"])

# The LIVE scheduled detectors. Anything listed here counts toward the panel's
# "last scan" / "active shocks" monitoring line. ADD A DETECTOR HERE WHEN YOU
# SCHEDULE IT — these two queries were pinned to 'shockguard_scan_v1' alone, so
# the IMERG rainfall advisory shipped, ran daily, and was completely invisible
# on the dashboard: its rows were never counted and its run never refreshed
# "last scan". A feed nobody can see is not a feed.
#   shockguard_scan_v1  — Sentinel-1 SAR drop + Sentinel-2 NDVI decline (07:30)
#   rainstorm_scan_v1   — GPM IMERG exceptional rainfall, flood precursor (08:00)
#   storm_scan_v1       — GPM IMERG half-hourly storm reconstruction (08:30)
LIVE_SCAN_SOURCES: tuple[str, ...] = (
    "shockguard_scan_v1", "rainstorm_scan_v1", "storm_scan_v1",
)
# The one live source whose point is a measured box on the ground (the per-LGA
# Sentinel scan) rather than an LGA-wide rainfall reading — the only ShockGuard
# rows that get field directions.
SATELLITE_SCAN_SOURCE = "shockguard_scan_v1"


FEED_LABELS: dict[str, str] = {
    "shockguard_scan_v1": "Sentinel-1 SAR / Sentinel-2 NDVI",
    "rainstorm_scan_v1": "GPM IMERG rainfall",
    "storm_scan_v1": "GPM IMERG storm intensity (half-hourly)",
}


async def _feed_statuses(
    session: AsyncSession, tenant_id: str,
) -> list["FeedStatus"]:
    """Health of each detector, reported separately.

    A single aggregated "last scan" hides a dead feed behind a live one — the
    SAR scan failed every run for weeks while the panel kept reading
    "continuously monitored" off the rainfall scan. Both the last SUCCESS and
    the last run of any outcome are returned, because "ran 5 minutes ago and
    failed" and "last succeeded 8 days ago" are both things an operator needs.
    """
    runs = (await session.execute(
        text(
            "SELECT DISTINCT ON (source) source, finished_at, status, "
            "       error_message "
            "  FROM public.ingestion_runs "
            " WHERE source IN :sources AND tenant_id = :t "
            " ORDER BY source, finished_at DESC"
        ).bindparams(sa_bindparam("sources", expanding=True)),
        {"sources": list(LIVE_SCAN_SOURCES), "t": tenant_id},
    )).mappings().all()
    last_ok = (await session.execute(
        text(
            "SELECT source, MAX(finished_at) AS ok_at "
            "  FROM public.ingestion_runs "
            " WHERE source IN :sources AND tenant_id = :t "
            "   AND status = 'succeeded' "
            " GROUP BY source"
        ).bindparams(sa_bindparam("sources", expanding=True)),
        {"sources": list(LIVE_SCAN_SOURCES), "t": tenant_id},
    )).mappings().all()
    counts = (await session.execute(
        text(
            "SELECT source, count(*) AS n FROM shock_events "
            " WHERE source IN :sources GROUP BY source"
        ).bindparams(sa_bindparam("sources", expanding=True)),
        {"sources": list(LIVE_SCAN_SOURCES)},
    )).mappings().all()

    by_run = {r["source"]: r for r in runs}
    by_ok = {r["source"]: r["ok_at"] for r in last_ok}
    by_count = {r["source"]: int(r["n"]) for r in counts}

    out: list[FeedStatus] = []
    for source in LIVE_SCAN_SOURCES:
        run = by_run.get(source)
        out.append(FeedStatus(
            source=source,
            label=FEED_LABELS.get(source, source),
            last_success_at=by_ok.get(source),
            last_run_at=run["finished_at"] if run else None,
            last_status=run["status"] if run else None,
            last_error=run["error_message"] if run else None,
            active_events=by_count.get(source, 0),
        ))
    return out


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


def _event_row(
    r: Mapping[str, Any],
    fallback: tuple[str | None, float | None, float | None] | None = None,
) -> ShockEventRow:
    """Map a `shock_events` row mapping to its API shape.

    `lon`/`lat` come from ST_X/ST_Y(location). When a row has no LGA / geometry
    (e.g. an older tenant-level scan), `fallback` — the tenant's representative
    (lga, lon, lat) — fills them so the feed and map always show a real place.
    Onset / area / population are nullable (ROI-level scans don't quantify them).
    """
    lon, lat = r.get("lon"), r.get("lat")
    lga = r.get("lga")
    metrics = r.get("metrics") or {}
    # A documented event whose source reported at STATE level has lga=NULL on
    # purpose. Backfilling the tenant's representative LGA there would put a
    # place name on the record that the source never named — e.g. showing the
    # 2024 Zamfara floods as "Talata Mafara". Take the fallback COORDINATES so
    # the map can still plot the state, but leave the label empty; the panel
    # renders `ev.lga ?? stateLabel`, which correctly reads as statewide.
    deliberately_statewide = (
        lga is None and metrics.get("lga_breakdown_published") is False
    )
    if fallback is not None:
        fb_lga, fb_lon, fb_lat = fallback
        if lga is None and not deliberately_statewide:
            lga = fb_lga
        if lon is None or lat is None:
            lon, lat = fb_lon, fb_lat
    location = (
        LonLat(lon=float(lon), lat=float(lat))
        if lon is not None and lat is not None else None
    )

    def _opt_int(v: Any) -> int | None:
        return int(v) if v is not None else None

    def _opt_float(v: Any) -> float | None:
        return float(v) if v is not None else None

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
        projected_onset_hours=_opt_int(r.get("projected_onset_hours")),
        affected_area_km2=_opt_float(r.get("affected_area_km2")),
        population_at_risk=_opt_int(r.get("population_at_risk")),
        lga=lga,
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
    live_notice: str | None = None
    if body.data_source == "live" and body.event_type == "flood":
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(tenant_id)}, public"),
        )
        try:
            live_series = await load_flood_series(session)
        except LiveDataMissingError as exc:
            # Degrade gracefully: fall back to the modelled detector and carry
            # a friendly notice rather than erroring the dashboard. Live SAR
            # coverage is sparse for some ROIs (~6-day Sentinel-1 repeat).
            live_notice = str(exc)

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
    # A detection may be STORED only from live SAR with nothing injected.
    # Drought is always modelled here and a flood falls back to a synthetic
    # series when live data is missing — both stay on screen, never in the
    # table (services/data_source.py). This is also what keeps a demo flood
    # from reaching the SMS path below.
    storable = may_store(
        used_live_data=live_series is not None,
        demo_injected=body.demo_inject_anomaly and live_series is None,
    )
    if body.persist and detection.triggered and not storable:
        live_notice = f"{live_notice} {STORED_ONLY_WHEN_LIVE}".strip() if live_notice else STORED_ONLY_WHEN_LIVE
    if body.persist and detection.triggered and storable:
        # Only persist actual triggered events. Negative scans are
        # informative but bloat the audit log if every dashboard load
        # writes "no flood today".
        event_id = await _persist_event(
            session,
            tenant_id=tenant_id, detection=detection,
            trace_id=_trace_id(request),
        )
        persisted = event_id is not None

        # Auto-trigger SMS to matching subscribers (best-effort, flag-gated —
        # off unless auto_notify_enabled + a system org with a signed DPA).
        if persisted:
            await fire_conflict_notification(
                tenant_id=tenant_id,
                severity=detection.severity,
                alert_type=detection.event_type,  # 'flood' | 'drought'
                lga=None,            # scan is tenant-level (no per-LGA input)
                zone_name=None,
                affected_area_ha=detection.affected_area_km2 * 100.0,
                livelihoods_at_risk=detection.population_at_risk,
                eta_hours=detection.projected_onset_hours,
                alert_id=event_id,
            )

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
            notice=live_notice,
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
    tenant_id = _require_tenant(request)

    # Proven-synthetic rows stay in the table but never reach a live view.
    where_clause = f"WHERE {NOT_SYNTHETIC}"
    params: dict[str, object] = {"limit": limit}
    if event_type:
        if event_type not in ("flood", "drought"):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported event_type {event_type!r}",
            )
        where_clause += " AND event_type = :event_type"
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

    fallback = lga_geo.representative_lga(tenant_id)
    events = [_event_row(r, fallback) for r in rows]

    # Field directions only for live satellite detections that carry their own
    # point (the measured box). Documented disasters, storms and rows plotted
    # at the state's borrowed point are area-level — a village on those would
    # send a team to the wrong place.
    places = await nearest_places(session, [
        (float(r["lon"]), float(r["lat"]))
        if r.get("source") == SATELLITE_SCAN_SOURCE and r.get("lga")
        and r.get("lon") is not None and r.get("lat") is not None else None
        for r in rows
    ])
    for ev, place in zip(events, places):
        ev.nearest_place = place

    # Monitoring status — each scheduled scan stamps public.ingestion_runs, so
    # the panel can show "scanned today, all clear" instead of looking stale
    # when shocks are (correctly) absent. active_shock_count is how many signals
    # the latest scans currently flag (their rows replace each run).
    #
    # BOTH live detectors count. These were pinned to 'shockguard_scan_v1'
    # alone, so the IMERG rainfall advisory (added 2026-07-27) ran daily and was
    # completely invisible on the dashboard: its rows never counted and its run
    # never refreshed "last scan". A feed nobody can see is not a feed.
    last_scan_at = (await session.execute(
        text(
            "SELECT MAX(finished_at) FROM public.ingestion_runs "
            "WHERE source IN :sources AND tenant_id = :t "
            "AND status = 'succeeded'"
        ).bindparams(sa_bindparam("sources", expanding=True)),
        {"sources": list(LIVE_SCAN_SOURCES), "t": tenant_id},
    )).scalar()
    active_shock_count = int((await session.execute(
        text(
            "SELECT count(*) FROM shock_events WHERE source IN :sources"
        ).bindparams(sa_bindparam("sources", expanding=True)),
        {"sources": list(LIVE_SCAN_SOURCES)},
    )).scalar() or 0)

    feeds = await _feed_statuses(session, tenant_id)

    return SuccessResponse(
        data=ShockEventListData(
            events=events,
            last_scan_at=last_scan_at,
            active_shock_count=active_shock_count,
            feeds=feeds,
        ),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )


# ─── Storms ───────────────────────────────────────────────────────────────

# Mirrors tasks/storm_scan.py MIN_BASELINE_DAYS. Under this many days of record
# for an LGA the scan measures and stores a storm but refuses to rate it, and
# the UI needs the same number to explain why nothing is rated yet.
STORM_MIN_BASELINE_DAYS = 21

# How many wettest-LGA rows the "scanned, nothing exceptional" evidence list
# carries. Enough to show the scan's reach, short enough to read at a glance.
STORM_MEASURED_LIMIT = 8


@router.get(
    "/storms",
    response_model=SuccessResponse[StormListData],
    summary="Recent storms reconstructed from half-hourly rainfall",
)
async def list_storms(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max storms (default 20).")
    ] = 20,
) -> SuccessResponse[StormListData]:
    """Storms, plus what was measured on the latest scanned day.

    A storm here is a MEASUREMENT — depth, rate, duration, and where that sits
    in the same LGA's own record. It is not a flood forecast: whether rain
    floods a place depends on drainage, saturation and how much ground is
    concrete, none of which this observes.

    The response deliberately carries `measured` alongside `storms` so an empty
    storms list is legible. "Scanned 142 LGAs, wettest hour 11 mm, nothing
    above the local 90th percentile" is a finding. An empty panel is not.
    """
    tenant_id = _require_tenant(request)

    storms = [
        StormRow(
            id=r["id"], tenant_id=r["tenant_id"], lga=r["lga"],
            location=(
                LonLat(lon=r["lon"], lat=r["lat"])
                if r["lon"] is not None and r["lat"] is not None else None
            ),
            started_at=r["started_at"], ended_at=r["ended_at"],
            peak_at=r["peak_at"],
            crosses_midnight_utc=bool(r["crosses_midnight_utc"]),
            peak_mm_hr=r["peak_mm_hr"], total_mm=r["total_mm"],
            max_1h_mm=r["max_1h_mm"], max_3h_mm=r["max_3h_mm"],
            max_6h_mm=r["max_6h_mm"], duration_h=r["duration_h"],
            percentile_1h=r["percentile_1h"], percentile_3h=r["percentile_3h"],
            baseline_days=r["baseline_days"], severity=r["severity"],
            detector_version=r["detector_version"], detected_at=r["detected_at"],
        )
        for r in (await session.execute(
            text(
                """
                SELECT id, tenant_id, lga, lon, lat, started_at, ended_at,
                       peak_at, crosses_midnight_utc, peak_mm_hr, total_mm,
                       max_1h_mm, max_3h_mm, max_6h_mm, duration_h,
                       percentile_1h, percentile_3h, baseline_days, severity,
                       detector_version, detected_at
                  FROM storm_events
                 ORDER BY started_at DESC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        )).mappings().all()
    ]

    # The most recent day that has ANY measurement, not "yesterday" — the Late
    # run can lag, and asking for a fixed date would render an empty panel on a
    # day the feed was merely slow.
    measured_day = (await session.execute(
        text("SELECT MAX(day) FROM storm_intensity_daily")
    )).scalar()

    measured: list[StormMeasurement] = []
    measured_lga_count = 0
    if measured_day is not None:
        measured_lga_count = int((await session.execute(
            text("SELECT count(*) FROM storm_intensity_daily WHERE day = :d"),
            {"d": measured_day},
        )).scalar() or 0)
        measured = [
            StormMeasurement(
                lga=r["lga"], day=r["day"], max_1h_mm=r["max_1h_mm"],
                max_3h_mm=r["max_3h_mm"], peak_mm_hr=r["peak_mm_hr"],
                slices_seen=r["slices_seen"],
                slices_expected=r["slices_expected"],
            )
            for r in (await session.execute(
                text(
                    """
                    SELECT lga, day, max_1h_mm, max_3h_mm, peak_mm_hr,
                           slices_seen, slices_expected
                      FROM storm_intensity_daily
                     WHERE day = :d
                     ORDER BY max_1h_mm DESC NULLS LAST
                     LIMIT :limit
                    """
                ),
                {"d": measured_day, "limit": STORM_MEASURED_LIMIT},
            )).mappings().all()
        ]

    # Distinct days of record, not row count: 400 LGAs on one day is one day of
    # baseline, and reporting 400 would imply a depth of history we do not have.
    baseline_days = int((await session.execute(
        text("SELECT count(DISTINCT day) FROM storm_intensity_daily")
    )).scalar() or 0)

    # The number that actually governs whether anything can be rated. A row
    # exists for an LGA only on days it rained there, so after a full 28-day
    # backfill a wet district may hold 27 days of its own record and a dry
    # one 4. Reporting only the calendar depth above would say "record
    # complete" while most of the territory was still unrankable.
    coverage = (await session.execute(
        text(
            "SELECT count(*) AS known, "
            "       count(*) FILTER (WHERE n >= :m) AS rateable "
            "  FROM (SELECT lga, count(*) AS n "
            "          FROM storm_intensity_daily GROUP BY lga) q"
        ),
        {"m": STORM_MIN_BASELINE_DAYS},
    )).mappings().one()

    last_scan_at = (await session.execute(
        text(
            "SELECT MAX(finished_at) FROM public.ingestion_runs "
            "WHERE source = :s AND tenant_id = :t AND status = 'succeeded'"
        ),
        {"s": "storm_scan_v1", "t": tenant_id},
    )).scalar()

    return SuccessResponse(
        data=StormListData(
            storms=storms,
            measured=measured,
            measured_day=measured_day,
            measured_lga_count=measured_lga_count,
            baseline_days=baseline_days,
            rateable_lgas=int(coverage["rateable"] or 0),
            known_lgas=int(coverage["known"] or 0),
            min_baseline_days=STORM_MIN_BASELINE_DAYS,
            last_scan_at=last_scan_at,
        ),
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

    # The scan is tenant/ROI-level (no per-LGA input), so attach a
    # representative LGA + coordinates instead of leaving the event placeless.
    lga, lon, lat = lga_geo.representative_lga(tenant_id)
    where = f" near {lga}" if lga else ""
    zone_name = f"{detection.event_type.capitalize()} signal (ROI-level){where}"

    await session.execute(
        text(
            """
            INSERT INTO shock_events (
                id, tenant_id, event_type, detector_name, detector_version,
                severity, confidence, confidence_band, requires_human_review,
                projected_onset_hours, affected_area_km2, population_at_risk,
                location, lga, zone_name,
                metrics, source, data_source, trace_id, created_at
            ) VALUES (
                :id, :tenant_id, :event_type, :detector_name, :detector_version,
                :severity, :confidence, :confidence_band, :requires_human_review,
                :projected_onset_hours, :affected_area_km2, :population_at_risk,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :lga, :zone_name,
                CAST(:metrics AS JSONB), :source, :data_source, :trace_id, :created_at
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
            "lon": lon, "lat": lat, "lga": lga, "zone_name": zone_name,
            "metrics": json.dumps(detection.metrics),
            "source": "detector_v1",
            "data_source": LIVE,
            "trace_id": trace_id,
            "created_at": datetime.now(timezone.utc),
        },
    )
    return event_id
