"""Async SQLAlchemy engine + tenant scoping for the notifications service."""
from __future__ import annotations

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

PILOT_TENANT_IDS: frozenset[str] = frozenset(
    {"kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "fct", "ghana", "senegal"}
)


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(
        s.database_url,
        echo=s.db_echo,
        pool_size=s.db_pool_size,
        max_overflow=s.db_pool_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def set_tenant_schema(session: AsyncSession, tenant_id: str) -> None:
    """Pin search_path to tenant_<id>, public. Allowlist-checked first."""
    if tenant_id not in PILOT_TENANT_IDS:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")
    await session.execute(text(f"SET search_path TO tenant_{tenant_id}, public"))


async def reset_to_public(session: AsyncSession) -> None:
    await session.execute(text("SET search_path TO public"))


def is_valid_tenant_id(tenant_id: str | None) -> bool:
    return bool(tenant_id) and tenant_id in PILOT_TENANT_IDS
