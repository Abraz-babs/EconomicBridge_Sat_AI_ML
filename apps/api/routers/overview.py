"""GET /api/v1/overview/stats — real, live platform-overview KPIs.

Cross-tenant roll-up: loops every pilot schema and counts what the feeds
actually hold (settlements scored from VIIRS+WorldPop, live crop-disease
detections from the trained ResNet, satellite observations, LGAs mapped).
No X-Tenant-Id — this is the platform-wide view the dashboard overview shows.

Counts are cheap and the endpoint is safe to poll; values are honest (every
number traces to a real row) and subtitles never fabricate a trend.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated
from fastapi import Depends

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.overview import (
    ActiveResponseData,
    ActiveResponseRow,
    CropHealthData,
    CropHealthRow,
    OverviewStatCard,
    OverviewStatsData,
)
from services.lga_geo import all_lgas
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name


router = APIRouter(prefix="/overview", tags=["overview"])


def _region(tenant_id: str) -> str:
    """Display name for a tenant id (fct -> FCT, else Title-case)."""
    if tenant_id == "fct":
        return "FCT"
    return tenant_id.replace("_", " ").title()


def _interleave(by_tenant: dict[str, list], limit: int, shift: int) -> list:
    """Round-robin across tenants so the result MIXES regions. `shift`
    rotates which region leads (day-of-year) so it re-orders over time."""
    order = sorted(by_tenant)
    if order:
        s = shift % len(order)
        order = order[s:] + order[:s]
    out: list = []
    depth = 0
    while len(out) < limit:
        progressed = False
        for t in order:
            pool = by_tenant[t]
            if depth < len(pool):
                out.append(pool[depth])
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
        depth += 1
    return out[:limit]

# The keyless/open feeds actually wired into the platform today.
LIVE_SOURCES: list[str] = [
    "Copernicus Sentinel-1/2",
    "NASA FIRMS",
    "VIIRS Black Marble",
    "WorldPop",
    "World Bank",
    "GIGA",
]


def _fmt(n: int) -> str:
    """Compact human number: 447, 1.2K, 3.4M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


@router.get(
    "/stats",
    response_model=SuccessResponse[OverviewStatsData],
    summary="Live, cross-tenant platform KPIs for the dashboard overview",
)
async def overview_stats(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[OverviewStatsData]:
    tenants = sorted(PILOT_TENANT_IDS)
    lgas_mapped = sum(len(all_lgas(t)) for t in tenants)

    settlements = 0
    crop_detections = 0
    sat_obs = 0
    for t in tenants:
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(t)}, public")
        )
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM poverty_villages) AS villages,
                      (SELECT COUNT(*) FROM crop_predictions
                         WHERE model_version LIKE '0.1.0%'
                           AND predicted_class NOT LIKE '%healthy') AS crop_det,
                      (SELECT COUNT(*) FROM satellite_observations
                         WHERE source = 'sentinel_stat_v1') AS sat_obs
                    """
                )
            )
        ).first()
        if row:
            settlements += int(row[0] or 0)
            crop_detections += int(row[1] or 0)
            sat_obs += int(row[2] or 0)

    cards = [
        OverviewStatCard(
            label="Pilot regions live",
            value=str(len(tenants)),
            subtitle="8 NG states + Ghana + Senegal",
            tone="ok",
        ),
        OverviewStatCard(
            label="LGAs mapped",
            value=_fmt(lgas_mapped),
            subtitle="real geoBoundaries admin-2",
            tone="ok",
        ),
        OverviewStatCard(
            label="Settlements scored",
            value=_fmt(settlements),
            subtitle="VIIRS night-lights + WorldPop",
            tone="ok",
        ),
        OverviewStatCard(
            label="Crop-disease detections",
            value=_fmt(crop_detections),
            # Counts REAL trained-model detections only (seeds excluded).
            # Zero is the honest state until field photos are uploaded — say
            # so, instead of looking broken next to a "live model" claim.
            subtitle=(
                "ResNet-50 · live model"
                if crop_detections
                else "ResNet-50 live · awaiting field uploads"
            ),
            tone="warn" if crop_detections else "ok",
        ),
    ]

    data = OverviewStatsData(
        tenants_live=len(tenants),
        lgas_mapped=lgas_mapped,
        settlements_scored=settlements,
        crop_detections=crop_detections,
        satellite_observations=sat_obs,
        live_sources=LIVE_SOURCES,
        cards=cards,
        generated_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(
        data=data,
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


def _tone_for_pct(pct: int) -> str:
    if pct >= 70:
        return "ok"
    if pct >= 45:
        return "warn"
    return "neg"


@router.get(
    "/crop_health",
    response_model=SuccessResponse[CropHealthData],
    summary="Live cross-tenant crop-health index (mixed regions)",
)
async def crop_health(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[CropHealthData]:
    """% of crop detections classified healthy, per crop × region, mixed
    across NG states + Ghana + Senegal. Includes BOTH real ResNet inference
    rows and the modelled baseline (0.0.0-seed): a real-only filter left the
    widget showing a single tenant (or nothing) until uploads accumulate.
    Real detections dominate naturally as they land; the dashboard subtitle
    declares the blend."""
    shift = datetime.now(timezone.utc).timetuple().tm_yday
    by_tenant: dict[str, list[CropHealthRow]] = {}
    for t in sorted(PILOT_TENANT_IDS):
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(t)}, public")
        )
        rows = (
            await session.execute(
                text(
                    """
                    SELECT split_part(predicted_class, '_', 1) AS crop,
                           COUNT(*) AS total,
                           SUM(CASE WHEN predicted_class LIKE '%healthy'
                                    THEN 1 ELSE 0 END) AS healthy
                      FROM crop_predictions
                     GROUP BY 1
                     HAVING COUNT(*) > 0
                     ORDER BY total DESC
                     LIMIT 2
                    """
                )
            )
        ).all()
        region = _region(t)
        out = []
        for crop, total, healthy in rows:
            pct = round(100 * int(healthy) / max(int(total), 1))
            out.append(
                CropHealthRow(
                    label=f"{str(crop).title()} — {region}",
                    pct=pct,
                    tone=_tone_for_pct(pct),
                )
            )
        if out:
            by_tenant[t] = out

    mixed = _interleave(by_tenant, limit=15, shift=shift)
    return SuccessResponse(
        data=CropHealthData(rows=mixed, generated_at=datetime.now(timezone.utc)),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


_SEVERITY_STATUS = {
    "critical": ("ACTIVE", "s-active"),
    "high": ("WATCH", "s-watch"),
    "medium": ("MONITOR", "s-monitor"),
    "low": ("RECOVERY", "s-recovery"),
}

# Events older than this stop wearing a live status chip. A month-old seed
# drought labelled "ACTIVE" during the rainy season reads as a live emergency
# and cost us credibility (user-reported 2026-07-14); severity chips are for
# CURRENT events, HISTORICAL is for kept examples and aged-out rows.
_ACTIVE_MAX_AGE_DAYS = 14


def shock_status(
    severity: str, source: str | None, created_at: datetime | None,
    now: datetime,
) -> tuple[str, str]:
    """Honest status chip for a shock event row.

    Seed rows and events older than _ACTIVE_MAX_AGE_DAYS are HISTORICAL
    (grey) regardless of severity — only recent detector rows wear a live
    severity chip.
    """
    age_days = (now - created_at).days if created_at is not None else 9999
    if source == "seed_v1" or age_days > _ACTIVE_MAX_AGE_DAYS:
        return "HISTORICAL", "s-historical"
    return _SEVERITY_STATUS.get(str(severity), ("MONITOR", "s-monitor"))


@router.get(
    "/active_response",
    response_model=SuccessResponse[ActiveResponseData],
    summary="Live cross-tenant active-response events (mixed regions)",
)
async def active_response(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ActiveResponseData]:
    """Recent shock events per region (flood/drought), mixed across NG states
    + Ghana + Senegal — real persisted rows, never off-plan countries."""
    shift = datetime.now(timezone.utc).timetuple().tm_yday
    by_tenant: dict[str, list[ActiveResponseRow]] = {}
    for t in sorted(PILOT_TENANT_IDS):
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(t)}, public")
        )
        rows = (
            await session.execute(
                text(
                    """
                    SELECT event_type, severity, lga, created_at, source
                      FROM shock_events
                     ORDER BY created_at DESC
                     LIMIT 3
                    """
                )
            )
        ).all()
        region = _region(t)
        now = datetime.now(timezone.utc)
        out = []
        for event_type, severity, lga, created_at, source in rows:
            status_label, tone = shock_status(
                str(severity), source, created_at, now,
            )
            dated = (
                f" · {created_at:%d %b}" if created_at is not None else ""
            )
            out.append(
                ActiveResponseRow(
                    region=f"{region} — {str(event_type).title()}",
                    sub=f"{lga or region} · {severity}{dated}",
                    status=status_label,
                    tone=tone,
                )
            )
        if out:
            by_tenant[t] = out

    mixed = _interleave(by_tenant, limit=12, shift=shift)
    return SuccessResponse(
        data=ActiveResponseData(rows=mixed, generated_at=datetime.now(timezone.utc)),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )
