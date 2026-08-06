"""Per-account usage tracking — buffered counters, periodic flush.

Answers the operator question "what is this account actually doing?" for
accounts that only ever *read* (partners, government beta users), which the
audit log cannot see because it records mutations only.

## Why buffered

Counting is on the hot path of every authenticated API request. A DB round
trip there would put write latency on every dashboard poll. So requests
increment an in-process dict and a background task flushes the accumulated
counts every `FLUSH_INTERVAL_SECONDS`. The flush is an UPSERT that *adds*
(`requests = account_activity.requests + EXCLUDED.requests`), which is what
makes it safe to run several API tasks behind the load balancer: each flushes
its own slice and Postgres sums them.

The trade is that an ungraceful kill loses at most one interval of counts.
That is the correct trade for usage statistics and would be the wrong one for
the audit log — which is precisely why these are separate tables.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 30

# Hard ceiling on distinct buffered keys. Reached only if the DB has been
# refusing writes for a long time; dropping counts beats growing without bound
# in a container with a memory limit. Normal steady state is a few dozen keys
# (accounts x tenants x modules seen in one 30s window).
MAX_BUFFER_KEYS = 20_000

# key -> (requests, last_seen)
_Key = tuple[str, str | None, date, str, str]
_buffer: dict[_Key, tuple[int, datetime]] = {}
_dropped = 0
_task: asyncio.Task | None = None


def record(
    *,
    user_id: str,
    org_id: str | None,
    tenant_id: str | None,
    module: str | None,
) -> None:
    """Count one request against an account. In-memory only — never blocks."""
    global _dropped
    now = datetime.now(timezone.utc)
    key: _Key = (user_id, org_id, now.date(), tenant_id or "", module or "")
    existing = _buffer.get(key)
    if existing is None:
        if len(_buffer) >= MAX_BUFFER_KEYS:
            _dropped += 1
            return
        _buffer[key] = (1, now)
    else:
        _buffer[key] = (existing[0] + 1, now)


async def flush() -> int:
    """Drain the buffer into `public.account_activity`. Returns rows written.

    The buffer is swapped out *before* any await so concurrent `record()` calls
    land in the fresh dict and are not lost to the in-flight write. If the write
    fails the counts are merged back rather than discarded.
    """
    global _buffer, _dropped
    if not _buffer:
        return 0
    pending, _buffer = _buffer, {}

    if _dropped:
        log.warning("activity: dropped %d counts (buffer ceiling)", _dropped)
        _dropped = 0

    rows = [
        {
            "user_id": user_id, "org_id": org_id, "day": day,
            "tenant_id": tenant_id, "module": module,
            "requests": count, "last_seen": last_seen,
        }
        for (user_id, org_id, day, tenant_id, module), (count, last_seen) in pending.items()
    ]

    from db.engine import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.account_activity
                        (user_id, org_id, day, tenant_id, module, requests, last_seen)
                    VALUES
                        (:user_id, :org_id, :day, :tenant_id, :module, :requests, :last_seen)
                    ON CONFLICT (user_id, day, tenant_id, module) DO UPDATE
                      SET requests  = account_activity.requests + EXCLUDED.requests,
                          last_seen = GREATEST(account_activity.last_seen,
                                               EXCLUDED.last_seen)
                    """
                ),
                rows,
            )
            await session.commit()
        return len(rows)
    except Exception:  # noqa: BLE001 — usage stats must never break the API
        for key, value in pending.items():
            prev = _buffer.get(key)
            _buffer[key] = value if prev is None else (
                prev[0] + value[0], max(prev[1], value[1])
            )
        log.exception("activity: flush failed, %d keys returned to buffer", len(pending))
        return 0


async def _loop() -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        await flush()


def start_flusher() -> None:
    """Start the background flush loop. Idempotent."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop_flusher() -> None:
    """Cancel the loop and flush what is buffered — called on shutdown."""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    await flush()


async def record_login(
    session: AsyncSession,
    *,
    user_id: Any,
    org_id: Any,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Append one row to the login history.

    Written inside the caller's login transaction — low volume, and an account's
    sign-in record is worth the same durability as the token it just minted.
    """
    await session.execute(
        text(
            """
            INSERT INTO public.account_login (user_id, org_id, ip_address, user_agent)
            VALUES (:uid, :oid, CAST(:ip AS INET), :ua)
            """
        ),
        {"uid": user_id, "oid": org_id, "ip": ip_address,
         "ua": (user_agent or "")[:500] or None},
    )


async def account_summary(session: AsyncSession, *, days: int = 30) -> list[dict]:
    """Per-account usage over the trailing `days`, busiest first.

    One row per user account, with the modules they touched folded into an
    array so the operator sees *what* an account uses, not just how much.
    """
    result = await session.execute(
        text(
            """
            WITH win AS (
                SELECT * FROM public.account_activity
                WHERE day >= CURRENT_DATE - CAST(:days AS INTEGER)
            )
            SELECT
                u.id                        AS user_id,
                u.email,
                u.full_name,
                u.role,
                u.is_active,
                u.last_login_at,
                o.name                      AS org_name,
                o.org_id                    AS org_slug,
                COALESCE(SUM(w.requests), 0)            AS requests,
                COUNT(DISTINCT w.day)                   AS active_days,
                MAX(w.last_seen)                        AS last_seen,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT NULLIF(w.module, '')), NULL)    AS modules,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT NULLIF(w.tenant_id, '')), NULL) AS tenants,
                (SELECT COUNT(*) FROM public.account_login l
                  WHERE l.user_id = u.id
                    AND l.at >= NOW() - MAKE_INTERVAL(days => CAST(:days AS INTEGER))
                ) AS logins
            FROM public.users u
            LEFT JOIN public.organisations o ON o.id = u.org_id
            LEFT JOIN win w ON w.user_id = u.id
            GROUP BY u.id, u.email, u.full_name, u.role, u.is_active,
                     u.last_login_at, o.name, o.org_id
            ORDER BY COALESCE(SUM(w.requests), 0) DESC, u.email
            """
        ),
        {"days": days},
    )
    return [dict(r) for r in result.mappings().all()]


async def account_detail(
    session: AsyncSession, *, user_id: UUID, days: int = 30
) -> dict:
    """Daily series + module/tenant breakdown + recent logins for one account."""
    daily = (await session.execute(
        text(
            """
            SELECT day, SUM(requests) AS requests
            FROM public.account_activity
            WHERE user_id = :uid AND day >= CURRENT_DATE - CAST(:days AS INTEGER)
            GROUP BY day ORDER BY day
            """
        ),
        {"uid": user_id, "days": days},
    )).mappings().all()

    by_module = (await session.execute(
        text(
            """
            SELECT NULLIF(module, '') AS module, SUM(requests) AS requests
            FROM public.account_activity
            WHERE user_id = :uid AND day >= CURRENT_DATE - CAST(:days AS INTEGER)
            GROUP BY module ORDER BY SUM(requests) DESC
            """
        ),
        {"uid": user_id, "days": days},
    )).mappings().all()

    by_tenant = (await session.execute(
        text(
            """
            SELECT NULLIF(tenant_id, '') AS tenant_id, SUM(requests) AS requests
            FROM public.account_activity
            WHERE user_id = :uid AND day >= CURRENT_DATE - CAST(:days AS INTEGER)
            GROUP BY tenant_id ORDER BY SUM(requests) DESC
            """
        ),
        {"uid": user_id, "days": days},
    )).mappings().all()

    logins = (await session.execute(
        text(
            """
            SELECT at, HOST(ip_address) AS ip_address, user_agent
            FROM public.account_login
            WHERE user_id = :uid ORDER BY at DESC LIMIT 25
            """
        ),
        {"uid": user_id},
    )).mappings().all()

    return {
        "daily": [dict(r) for r in daily],
        "by_module": [dict(r) for r in by_module],
        "by_tenant": [dict(r) for r in by_tenant],
        "logins": [dict(r) for r in logins],
    }
