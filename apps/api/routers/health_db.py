"""GET /api/v1/health/db — verify database connectivity.

Separate from `/health` because it requires a live DB connection. Used by
operators and CI to confirm the migration ran and the API can talk to Postgres.

Returns the standard response envelope. On failure, returns HTTP 503 with
`error.code = "DATABASE_UNREACHABLE"`.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import (
    ErrorDetail,
    ErrorResponse,
    ResponseMeta,
    SuccessResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


class DbHealthData(BaseModel):
    """Body for GET /api/v1/health/db on success."""

    status: str
    server_version: str
    has_postgis: bool
    has_timescaledb: bool


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


@router.get("/db", response_model=SuccessResponse[DbHealthData])
async def health_db(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SuccessResponse[DbHealthData] | JSONResponse:
    """Probe the database — return server version and extension availability."""

    trace = _trace_id(request)
    try:
        version_row = await session.execute(text("SHOW server_version"))
        version = str(version_row.scalar_one()).strip()

        ext_row = await session.execute(
            text(
                "SELECT extname FROM pg_extension "
                "WHERE extname IN ('postgis', 'timescaledb')"
            )
        )
        installed = {row[0] for row in ext_row.all()}

        return SuccessResponse(
            data=DbHealthData(
                status="ok",
                server_version=version,
                has_postgis="postgis" in installed,
                has_timescaledb="timescaledb" in installed,
            ),
            meta=ResponseMeta(
                tenant_id=None,
                trace_id=trace,
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except SQLAlchemyError as exc:
        body = ErrorResponse(
            error=ErrorDetail(
                code="DATABASE_UNREACHABLE",
                message=f"Could not query the database: {exc.__class__.__name__}",
                trace_id=trace,
            ),
            meta=ResponseMeta(
                tenant_id=None,
                trace_id=trace,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(mode="json"),
        )
