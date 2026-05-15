"""Standard response envelope (CLAUDE.md §7).

Mirrors apps/api/schemas/envelope.py. Each service owns its own copy so the
ML microservice is independently deployable.
"""
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Pagination(BaseModel):
    page: int
    per_page: int
    total: int


class ResponseMeta(BaseModel):
    tenant_id: str | None = None
    trace_id: UUID
    timestamp: datetime
    pagination: Pagination | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: UUID


class SuccessResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(populate_by_name=True)
    success: bool = True
    data: T
    meta: ResponseMeta
    error: None = None


class ErrorResponse(BaseModel):
    success: bool = False
    data: None = None
    meta: ResponseMeta
    error: ErrorDetail
