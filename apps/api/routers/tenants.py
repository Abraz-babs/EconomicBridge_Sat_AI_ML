"""GET /api/v1/tenant-info — verification probe for the TenantContext middleware.

Echoes the active tenant_id and the Postgres `current_schema()` so callers
(and integration tests) can confirm the header-based scoping is in effect.
Public endpoint — no auth required.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse

router = APIRouter(prefix="/tenant-info", tags=["tenants"])


class TenantInfoData(BaseModel):
    """Body of GET /api/v1/tenant-info."""

    tenant_id: str | None
    db_current_schema: str
    db_search_path: str


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.get("", response_model=SuccessResponse[TenantInfoData])
async def tenant_info(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SuccessResponse[TenantInfoData]:
    """Return the active tenant context as the API sees it."""

    tenant_id: str | None = getattr(request.state, "tenant_id", None)

    current_schema = (await session.execute(text("SELECT current_schema()"))).scalar_one()
    search_path = (await session.execute(text("SHOW search_path"))).scalar_one()

    trace = _trace_id(request)
    # Convert the tenant_id string to UUID-or-null for the envelope meta.
    # We store tenant_id as a string in state (it's a slug like "kebbi"), so we
    # leave meta.tenant_id null here — the data block carries the slug.
    return SuccessResponse(
        data=TenantInfoData(
            tenant_id=tenant_id,
            db_current_schema=str(current_schema),
            db_search_path=str(search_path),
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=trace,
            timestamp=datetime.now(timezone.utc),
        ),
    )
