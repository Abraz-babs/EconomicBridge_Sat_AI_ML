"""Standard API response envelope (CLAUDE.md §7).

Every API response uses this structure so clients can rely on a single shape across
all endpoints. The envelope is constructed via the `make_success` / `make_error`
helpers — callers should not instantiate the dataclasses directly.
"""
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Pagination(BaseModel):
    """Pagination block included in `meta.pagination` for list endpoints."""

    page: int
    per_page: int
    total: int


class ResponseMeta(BaseModel):
    """Metadata block included in every response envelope."""

    tenant_id: UUID | None = None
    trace_id: UUID
    timestamp: datetime
    pagination: Pagination | None = None


class ErrorDetail(BaseModel):
    """Structured error payload (CLAUDE.md §7)."""

    code: str
    message: str
    trace_id: UUID


class SuccessResponse(BaseModel, Generic[T]):
    """Success envelope. `data` is the endpoint-specific payload."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    data: T
    meta: ResponseMeta
    error: None = None


class ErrorResponse(BaseModel):
    """Error envelope. Mirrors SuccessResponse with `data: null`."""

    success: bool = False
    data: None = None
    meta: ResponseMeta
    error: ErrorDetail


def build_meta(
    trace_id: UUID | None = None,
    tenant_id: UUID | None = None,
    pagination: Pagination | None = None,
) -> ResponseMeta:
    """Construct a ResponseMeta with sensible defaults for non-RBAC routes."""

    return ResponseMeta(
        tenant_id=tenant_id,
        trace_id=trace_id or uuid4(),
        timestamp=datetime.now(timezone.utc),
        pagination=pagination,
    )
