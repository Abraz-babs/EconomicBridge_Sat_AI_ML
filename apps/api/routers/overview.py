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
from schemas.overview import OverviewStatCard, OverviewStatsData
from services.lga_geo import all_lgas
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name


router = APIRouter(prefix="/overview", tags=["overview"])

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
            subtitle="ResNet-50 · live model",
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
