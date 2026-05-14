"""Async SQLAlchemy engine + session factory.

Every request that needs DB access acquires a session via the `get_session`
FastAPI dependency. If the request carries a validated tenant_id on
`request.state` (placed there by TenantContextMiddleware), the session issues
`SET search_path TO tenant_{id}, public` before yielding — every query in the
handler runs against that schema by default (CLAUDE.md §4.2, ADR-001).

The engine is created lazily on first use so `import config` does not trigger
a connection attempt (important for tests and Alembic).
"""
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings
from services.tenants import is_valid_tenant_id, tenant_schema_name


@lru_cache
def get_engine() -> AsyncEngine:
    """Return a process-wide async engine (cached)."""

    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a cached AsyncSession factory bound to the engine."""

    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a tenant-scoped AsyncSession.

    Rolls back on exception, commits on clean return. If `request.state.tenant_id`
    is set (by TenantContextMiddleware), the session's search_path is pinned to
    that tenant's schema for the duration of the request.

    Identifier safety: tenant_id is re-validated against the allowlist here so
    the string is never trusted blindly when composing the SET statement.
    """
    factory = get_session_factory()
    tenant_id = getattr(request.state, "tenant_id", None)

    async with factory() as session:
        if tenant_id and is_valid_tenant_id(tenant_id):
            schema = tenant_schema_name(tenant_id)
            # search_path is a session-level setting; PostgreSQL does NOT accept
            # bind parameters for SET. We validated tenant_id twice (middleware
            # + here) so f-string interpolation is safe.
            await session.execute(text(f"SET search_path TO {schema}, public"))
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
