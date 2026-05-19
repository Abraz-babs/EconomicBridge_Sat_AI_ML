"""Async SQLAlchemy engine + session factory for the ingestion service.

Lives in its own module (not imported from apps/api) to keep the microservice
boundary clean — each service owns its connection pool.

The ingestion service writes across tenant schemas in a single run, so
`set_tenant_schema` is exposed as an explicit helper instead of being applied
per-request. Tasks call it before writing tenant-scoped data.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

PILOT_TENANT_IDS: frozenset[str] = frozenset(
    {
        # Created by migration 0002
        "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
        "fct", "ghana", "senegal",
        # Added by migration 0008
        "nasarawa",
    }
)


@lru_cache
def get_engine() -> AsyncEngine:
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
    return async_sessionmaker(
        bind=get_engine(), expire_on_commit=False, autoflush=False
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a session, commits on clean exit."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def set_tenant_schema(session: AsyncSession, tenant_id: str) -> None:
    """Pin the session's search_path to `tenant_<id>`. Raises on unknown tenant.

    The tenant_id is checked against the allowlist before interpolation. SET
    search_path does not accept bind parameters, so f-string is the only path —
    the allowlist check is what makes it safe.
    """
    if tenant_id not in PILOT_TENANT_IDS:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")
    await session.execute(text(f"SET search_path TO tenant_{tenant_id}, public"))


def is_valid_tenant_id(tenant_id: str | None) -> bool:
    return bool(tenant_id) and tenant_id in PILOT_TENANT_IDS
