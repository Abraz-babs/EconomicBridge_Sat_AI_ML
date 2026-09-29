"""The Overview's live panels — each number read from what the feeds recorded.

Built 2026-09-29 to replace hard-coded panels (operator: "make anything fake
become real"):

* GET /overview/system_status — the footer status bar. It used to list five
  feeds with typed-in latencies, a random "last ingestion" timestamp, a fixed
  "Uptime 99.7%", and three "AI models" with statuses nobody set. Now: every
  monitored feed with its last successful run and whether that is within its
  own cadence (the same budgets the feed watchdog enforces). Uptime is not
  measured, so it is not shown.
* GET /overview/readings_trend — the "Coverage trend" panel. It was six
  invented bars ("mapped households / month"). Now: readings each feed stored
  per month, from public.ingestion_runs.
* GET /overview/signals — the Overview map. It coloured each state by a
  typed-in "conflict risk" (critical/high/medium/low) that no data produced.
  Now: per pilot, what the satellites flagged in the last 14 days (storms,
  live radar/greenness detections), open land alerts from the last 30 days,
  and the share of villages dark at night.

No X-Tenant-Id: platform-wide, like /overview/stats. Counts only — no names,
no numbers of people's phones, nothing per person.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from services.data_source import NOT_SYNTHETIC, REAL_ALERT
from services.feed_health import FEED_MAX_AGE_HOURS
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name

router = APIRouter(prefix="/overview", tags=["overview"])

# What each monitored feed reads, in words a visitor recognises.
FEED_LABELS: dict[str, str] = {
    "MODIS_NRT": "NASA FIRMS fires",
    "encroachment_detector_v1": "Land-disturbance watch · Sentinel-1/2",
    "shockguard_scan_v1": "Radar and greenness checks · Sentinel-1/2",
    "rainstorm_scan_v1": "Daily rainfall · NASA GPM IMERG",
    "storm_scan_v1": "Storms, half-hourly · NASA GPM IMERG",
    "food_prices_v1": "Food prices · FEWS NET, NBS",
    "wb_rtp_v1": "Market prices · World Bank",
    "land_change_v1": "Whole-LGA land change · Sentinel-2",
}
SIGNAL_DAYS = 14
LAND_ALERT_DAYS = 30


# ─── schemas ──────────────────────────────────────────────────────────────


class FeedState(BaseModel):
    source: str
    label: str
    last_success_at: datetime | None = None
    last_status: str | None = None
    max_age_hours: int
    current: bool = False


class SystemStatusData(BaseModel):
    feeds: list[FeedState] = Field(default_factory=list)
    current: int = 0
    total: int = 0
    last_ingestion_at: datetime | None = None


class MonthReadings(BaseModel):
    month: date
    readings: int
    runs: int


class ReadingsTrendData(BaseModel):
    months: list[MonthReadings] = Field(default_factory=list)


class PilotSignals(BaseModel):
    tenant_id: str
    storms: int = 0                 # half-hourly storm events, last 14 days
    detections: int = 0             # live radar / greenness detections, last 14 days
    land_alerts: int = 0            # open land alerts raised in the last 30 days
    villages: int = 0               # GRID3 villages measured for light
    dark_villages: int = 0
    total: int = 0                  # storms + detections + land_alerts


class SignalsData(BaseModel):
    days: int = SIGNAL_DAYS
    land_alert_days: int = LAND_ALERT_DAYS
    pilots: list[PilotSignals] = Field(default_factory=list)


# ─── pure helpers (tested without a database) ────────────────────────────


def feed_states(rows: Sequence[Mapping[str, Any]], now: datetime) -> list[FeedState]:
    """One entry per MONITORED feed, current when its last success is within budget."""
    seen = {r["source"]: r for r in rows}
    out: list[FeedState] = []
    for source, budget in FEED_MAX_AGE_HOURS.items():
        r = seen.get(source) or {}
        ok_at = r.get("ok_at")
        out.append(FeedState(
            source=source, label=FEED_LABELS.get(source, source),
            last_success_at=ok_at, last_status=r.get("last_status"), max_age_hours=budget,
            current=bool(ok_at and (now - ok_at) <= timedelta(hours=budget)),
        ))
    return out


def month_series(rows: Sequence[Mapping[str, Any]], today: date, months: int = 6) -> list[MonthReadings]:
    """The last `months` calendar months, oldest first; a month with no runs reads 0."""
    by = {(r["month"].year, r["month"].month): r for r in rows}
    y, m = today.year, today.month
    keys: list[tuple[int, int]] = []
    for _ in range(months):
        keys.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    out = []
    for y, m in reversed(keys):
        r = by.get((y, m)) or {}
        out.append(MonthReadings(month=date(y, m, 1), readings=int(r.get("readings") or 0),
                                 runs=int(r.get("runs") or 0)))
    return out


def _meta(request: Request) -> ResponseMeta:
    return ResponseMeta(tenant_id=None, trace_id=getattr(request.state, "trace_id", uuid4()),
                        timestamp=datetime.now(timezone.utc), pagination=None)


# ─── endpoints ────────────────────────────────────────────────────────────


@router.get("/system_status", response_model=SuccessResponse[SystemStatusData],
            summary="Every monitored feed and whether it is current")
async def system_status(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[SystemStatusData]:
    rows = (await session.execute(text(
        """
        SELECT source,
               MAX(finished_at) FILTER (WHERE status = 'succeeded') AS ok_at,
               (ARRAY_AGG(status ORDER BY finished_at DESC NULLS LAST))[1] AS last_status
          FROM public.ingestion_runs
         WHERE source = ANY(:sources)
         GROUP BY source
        """
    ), {"sources": list(FEED_MAX_AGE_HOURS)})).mappings().all()
    last = (await session.execute(text(
        "SELECT MAX(finished_at) FROM public.ingestion_runs WHERE status = 'succeeded'"
    ))).scalar()
    feeds = feed_states(list(rows), datetime.now(timezone.utc))
    return SuccessResponse(data=SystemStatusData(
        feeds=feeds, current=sum(f.current for f in feeds), total=len(feeds),
        last_ingestion_at=last,
    ), meta=_meta(request))


@router.get("/readings_trend", response_model=SuccessResponse[ReadingsTrendData],
            summary="Readings the feeds stored, per month, for the last six months")
async def readings_trend(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ReadingsTrendData]:
    today = date.today()
    y, m = today.year, today.month - 5          # the first of the six months shown
    while m <= 0:
        y, m = y - 1, m + 12
    since = date(y, m, 1)
    rows = (await session.execute(text(
        """
        SELECT date_trunc('month', finished_at)::date AS month,
               COALESCE(SUM(records_ingested), 0) AS readings, COUNT(*) AS runs
          FROM public.ingestion_runs
         WHERE status = 'succeeded' AND finished_at >= :since
         GROUP BY 1
        """
    ), {"since": since})).mappings().all()
    return SuccessResponse(data=ReadingsTrendData(months=month_series(list(rows), today)),
                           meta=_meta(request))


@router.get("/signals", response_model=SuccessResponse[SignalsData],
            summary="What the satellites flagged in each pilot recently")
async def signals(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[SignalsData]:
    now = datetime.now(timezone.utc)
    present = {
        (r[0], r[1]) for r in (await session.execute(text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_name = ANY(:names)"
        ), {"names": ["storm_events", "shock_events", "alert_events", "village_light"]})).all()
    }
    pilots: list[PilotSignals] = []
    for t in sorted(PILOT_TENANT_IDS):
        schema = tenant_schema_name(t)
        p = PilotSignals(tenant_id=t)
        if (schema, "storm_events") in present:
            p.storms = int((await session.execute(text(
                f'SELECT COUNT(*) FROM "{schema}".storm_events WHERE peak_at >= :d'
            ), {"d": now - timedelta(days=SIGNAL_DAYS)})).scalar() or 0)
        if (schema, "shock_events") in present:
            p.detections = int((await session.execute(text(
                f'SELECT COUNT(*) FROM "{schema}".shock_events '
                f"WHERE source = 'shockguard_scan_v1' AND {NOT_SYNTHETIC} AND created_at >= :d"
            ), {"d": now - timedelta(days=SIGNAL_DAYS)})).scalar() or 0)
        if (schema, "alert_events") in present:
            p.land_alerts = int((await session.execute(text(
                f'SELECT COUNT(*) FROM "{schema}".alert_events '
                f"WHERE is_deleted = FALSE AND status = 'pending_review' AND {REAL_ALERT} "
                "AND created_at >= :d"
            ), {"d": now - timedelta(days=LAND_ALERT_DAYS)})).scalar() or 0)
        if (schema, "village_light") in present:
            v = (await session.execute(text(
                f'SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE light_class = \'unlit\') AS dark '
                f'FROM "{schema}".village_light '
                f'WHERE period = (SELECT max(period) FROM "{schema}".village_light)'
            ))).mappings().one()
            p.villages, p.dark_villages = int(v["n"] or 0), int(v["dark"] or 0)
        p.total = p.storms + p.detections + p.land_alerts
        pilots.append(p)
    return SuccessResponse(data=SignalsData(pilots=pilots), meta=_meta(request))
