"""Public health-check endpoint.

Used by the frontend, load balancers, and uptime monitors. Returns the standard
response envelope from CLAUDE.md §7. No authentication required.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config import get_settings
from schemas.envelope import ResponseMeta, SuccessResponse

router = APIRouter(prefix="/health", tags=["health"])


class HealthData(BaseModel):
    """Body returned in `data` for GET /api/v1/health."""

    status: str
    service: str
    version: str
    app_env: str


@router.get("", response_model=SuccessResponse[HealthData])
async def health(request: Request) -> SuccessResponse[HealthData]:
    """Return service liveness information wrapped in the standard envelope."""

    settings = get_settings()
    trace_id: UUID = getattr(request.state, "trace_id", uuid4())

    return SuccessResponse(
        data=HealthData(
            status="ok",
            service=settings.app_name,
            version=settings.app_version,
            app_env=settings.app_env,
        ),
        meta=ResponseMeta(
            # The tenant is a slug ("kebbi"), not a UUID, so it cannot go in
            # this field: passing it turned a liveness probe into a 500 for
            # any caller that sends X-Tenant-Id (the dashboard always does).
            tenant_id=None,
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc),
        ),
    )
