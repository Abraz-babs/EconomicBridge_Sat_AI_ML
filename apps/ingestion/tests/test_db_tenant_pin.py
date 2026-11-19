"""The tenant pin must outlive a commit.

search_path is per database connection, and a session hands its connection
back to the pool at every commit. Pinning once and then committing inside a
loop therefore let later statements run in whatever schema the next pooled
connection last had. Found 2026-11-19 behind two real faults: a farmer SMS
that went out unrecorded (2026-09-14), and a Niger fire alert filed in
tenant_kebbi.alert_events. These tests pin the mechanism; the behaviour
against a real Postgres pool was proved on the live database the same day.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

import db


class _Session:
    """Duck-typed AsyncSession: records SQL, carries `info` like the real one."""

    def __init__(self) -> None:
        self.info: dict[str, str] = {}
        self.sql: list[str] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN201 — duck-typed
        self.sql.append(" ".join(str(stmt).split()))


class _Connection:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def exec_driver_sql(self, sql: str) -> None:
        self.sql.append(sql)


@pytest.mark.asyncio
async def test_pin_is_recorded_and_applied_to_the_current_transaction() -> None:
    s = _Session()
    await db.set_tenant_schema(s, "kebbi")
    assert s.info[db.TENANT_SCHEMA_KEY] == "tenant_kebbi"
    # LOCAL: the path dies with the transaction, so no pooled connection
    # carries a tenant's schema to the next borrower.
    assert s.sql == ["SET LOCAL search_path TO tenant_kebbi, public"]


@pytest.mark.asyncio
async def test_pinning_again_moves_the_pin() -> None:
    s = _Session()
    await db.set_tenant_schema(s, "kebbi")
    await db.set_tenant_schema(s, "niger")
    assert s.info[db.TENANT_SCHEMA_KEY] == "tenant_niger"


@pytest.mark.asyncio
async def test_unknown_tenant_is_refused_before_anything_is_pinned() -> None:
    s = _Session()
    with pytest.raises(ValueError):
        await db.set_tenant_schema(s, "kebbi, public; DROP SCHEMA public")
    assert s.info == {}
    assert s.sql == []


def test_every_new_transaction_re_applies_the_pin() -> None:
    """The hook that runs when a transaction begins on a (possibly different)
    pooled connection — the half of the fix a single SET could never provide."""

    class _Pinned:
        info = {db.TENANT_SCHEMA_KEY: "tenant_niger"}

    conn = _Connection()
    db._repin_tenant_schema(_Pinned(), None, conn)
    assert conn.sql == ["SET LOCAL search_path TO tenant_niger, public"]


def test_an_unpinned_session_is_left_alone() -> None:
    class _Unpinned:
        info: dict[str, str] = {}

    conn = _Connection()
    db._repin_tenant_schema(_Unpinned(), None, conn)
    assert conn.sql == []


def test_ingestion_sessions_carry_the_hook() -> None:
    assert event.contains(db.TenantPinnedSession, "after_begin", db._repin_tenant_schema)
    factory = db.get_session_factory()      # builds the engine lazily; no connection made
    assert factory.kw["sync_session_class"] is db.TenantPinnedSession
