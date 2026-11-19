"""Async SQLAlchemy engine + session factory for the ingestion service.

Lives in its own module (not imported from apps/api) to keep the microservice
boundary clean — each service owns its connection pool.

The ingestion service writes across tenant schemas in a single run, so
`set_tenant_schema` is exposed as an explicit helper instead of being applied
per-request. Tasks call it before writing tenant-scoped data.

A pin lasts for the life of the SESSION, across commits — see
`_repin_tenant_schema` for why that needs a hook rather than one SET.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

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


# session.info key naming the schema a session is pinned to.
TENANT_SCHEMA_KEY = "tenant_schema"


class TenantPinnedSession(Session):
    """The sync Session behind every ingestion AsyncSession.

    A class of its own so the hook below applies to this service's sessions
    only, never to a Session some library creates.
    """


@event.listens_for(TenantPinnedSession, "after_begin")
def _repin_tenant_schema(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Re-apply a pinned tenant's search_path at the start of EVERY transaction.

    search_path belongs to the database connection, not to the session. A
    session gives its connection back to the pool at every commit, and the
    next transaction may check out a different one, carrying whatever path
    that connection last had: none, or another tenant's. So "pin once, then
    commit inside a loop" wrote to the wrong place after the first commit.
    Both cases were found on 2026-11-19:

    * on 2026-09-14 a farmer SMS went out but was never recorded, because the
      stamp after the first commit ran in another tenant's schema and matched
      no row;
    * in November 2026 a Niger fire alert was written into
      tenant_kebbi.alert_events.

    SET LOCAL lasts only until the transaction ends, so no connection carries
    a tenant path back to the pool either.
    """
    schema = session.info.get(TENANT_SCHEMA_KEY)
    if schema:
        connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}, public")


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
        sync_session_class=TenantPinnedSession,
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
    """Pin the session to `tenant_<id>`, now and after every later commit.

    Raises on an unknown tenant. The tenant_id is checked against the
    allowlist before interpolation. SET search_path does not accept bind
    parameters, so an f-string is the only way, and the allowlist check is
    what makes it safe.

    The SET LOCAL covers the current transaction. The pin recorded in
    `session.info` makes `_repin_tenant_schema` cover every later one.
    Calling it again with another tenant moves the pin.
    """
    if tenant_id not in PILOT_TENANT_IDS:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")
    schema = f"tenant_{tenant_id}"
    session.info[TENANT_SCHEMA_KEY] = schema
    await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))


def is_valid_tenant_id(tenant_id: str | None) -> bool:
    return bool(tenant_id) and tenant_id in PILOT_TENANT_IDS
