"""GET /api/v1/intelligence/feed — cross-tenant activity stream.

Powers the Overview-tab Intelligence Feed + Alert Bar. Pulls the most
recent rows from every signal-producing table (FIRMS alerts, NDVI
anomalies, shock events, aid coverage uploads, poverty rows),
normalizes them into a single time-sorted stream, and returns the
top N.

No X-Tenant-Id required — this is the platform-wide view by design.
Per-tenant filtering happens in the per-module panels via their
existing routers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.intelligence_feed import FeedEventModel, IntelligenceFeedData
from services.intelligence_feed import gather_feed


router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.get(
    "/feed",
    response_model=SuccessResponse[IntelligenceFeedData],
    summary="Recent cross-tenant intelligence events for the Overview tab",
)
async def get_intelligence_feed(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max events returned (default 20).")
    ] = 20,
) -> SuccessResponse[IntelligenceFeedData]:
    events = await gather_feed(session, limit=limit)
    return SuccessResponse(
        data=IntelligenceFeedData(
            events=[
                FeedEventModel(
                    kind=e.kind, tenant_id=e.tenant_id, title=e.title,
                    region=e.region, tag=e.tag, severity=e.severity,
                    source=e.source, observed_at=e.observed_at,
                )
                for e in events
            ],
            total=len(events),
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )
