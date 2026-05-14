"""
Database Engine and Tenant Context — EconomicBridge
=====================================================
Provides the async SQLAlchemy engine, session factory, and TenantContext
middleware for schema-per-tenant isolation.

Usage in FastAPI:
    from core.database import get_db, TenantContextMiddleware

    app.add_middleware(TenantContextMiddleware)

    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)):
        ...
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text


# ─────────────────────────────────────────
# Context variable for current tenant
# ─────────────────────────────────────────

_current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)
_current_trace_id: ContextVar[str] = ContextVar(
    "current_trace_id", default=""
)


def get_current_tenant() -> str | None:
    """Get the current tenant ID from context.

    Returns:
        Current tenant ID string, or None if not set.
    """
    return _current_tenant.get()


def set_current_tenant(tenant_id: str | None) -> None:
    """Set the current tenant ID in context.

    Args:
        tenant_id: Tenant identifier to set.
    """
    _current_tenant.set(tenant_id)


def get_trace_id() -> str:
    """Get the current request trace ID.

    Returns:
        Trace ID string for the current request.
    """
    trace = _current_trace_id.get()
    if not trace:
        trace = str(uuid.uuid4())
        _current_trace_id.set(trace)
    return trace


# ─────────────────────────────────────────
# Engine and Session Factory
# ─────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://economicbridge:devpassword@localhost:5432/economicbridge",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─────────────────────────────────────────
# Base Model
# ─────────────────────────────────────────


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# ─────────────────────────────────────────
# Session Dependency
# ─────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session.

    Sets the PostgreSQL search_path to the current tenant's schema
    before yielding the session. This ensures all queries are
    automatically scoped to the correct tenant.

    Yields:
        AsyncSession with tenant schema set.

    Raises:
        ValueError: If no tenant context is set.
    """
    tenant_id = get_current_tenant()
    if tenant_id is None:
        raise ValueError(
            "No tenant context set. Ensure TenantContextMiddleware "
            "is active and the request includes a valid JWT."
        )

    schema_name = f"tenant_{tenant_id}"

    async with async_session_factory() as session:
        # Set the search_path to the tenant's schema
        await session.execute(
            text(f"SET search_path TO {schema_name}, public")
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_no_tenant() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for queries that don't require tenant context.

    Use sparingly — only for admin endpoints and authentication.

    Yields:
        AsyncSession using the public schema.
    """
    async with async_session_factory() as session:
        await session.execute(text("SET search_path TO public"))
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─────────────────────────────────────────
# TenantContext Middleware
# ─────────────────────────────────────────


class TenantContextMiddleware:
    """ASGI middleware that extracts tenant_id from JWT and sets context.

    The tenant_id is extracted from the JWT token's claims and stored
    in a context variable. All subsequent database operations in the
    request will use this tenant's schema.

    This middleware also generates a unique trace_id for each request
    for audit logging and error tracking.
    """

    def __init__(self, app: Any) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application.
        """
        self.app = app

    async def __call__(
        self, scope: dict, receive: Any, send: Any
    ) -> None:
        """Process an ASGI request.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Generate trace_id for this request
        trace_id = str(uuid.uuid4())
        _current_trace_id.set(trace_id)

        # Extract tenant_id from request state
        # (Set by the auth dependency after JWT validation)
        # The actual JWT decoding is handled by the auth dependency,
        # which sets scope["state"]["tenant_id"].
        tenant_id = scope.get("state", {}).get("tenant_id")

        if tenant_id:
            set_current_tenant(tenant_id)

        try:
            await self.app(scope, receive, send)
        finally:
            # Clean up context
            set_current_tenant(None)
            _current_trace_id.set("")
