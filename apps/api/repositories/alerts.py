"""Repository for the per-tenant alert_events table.

Queries assume the session's `search_path` is pinned to the correct tenant by
`db.engine.get_session` — no schema name appears in any SQL here. If a query
hits this layer without tenant scoping it will fail (no public.alert_events
table exists), which is the intended safety property.

Only raw DB access lives here. Filtering rules that touch business semantics
(e.g. "soft-deleted rows are hidden by default") live in services.farmland.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_event import AlertEvent
from schemas.farmland import (
    AlertListQuery,
    AlertSeverity,
    AlertStatus,
    AlertType,
)


def _apply_filters(
    stmt: Select,
    *,
    severity: Sequence[AlertSeverity] | None,
    status: Sequence[AlertStatus] | None,
    alert_type: Sequence[AlertType] | None,
    lga: str | None,
    since: datetime | None,
    until: datetime | None,
    include_deleted: bool,
) -> Select:
    """Apply the query's WHERE clauses. Returns a new Select."""
    if not include_deleted:
        stmt = stmt.where(AlertEvent.is_deleted.is_(False))
    if severity:
        stmt = stmt.where(AlertEvent.severity.in_([s.value for s in severity]))
    if status:
        stmt = stmt.where(AlertEvent.status.in_([s.value for s in status]))
    if alert_type:
        stmt = stmt.where(AlertEvent.alert_type.in_([t.value for t in alert_type]))
    if lga:
        stmt = stmt.where(AlertEvent.lga == lga)
    if since:
        stmt = stmt.where(AlertEvent.created_at >= since)
    if until:
        stmt = stmt.where(AlertEvent.created_at <= until)
    return stmt


async def list_alerts(
    session: AsyncSession,
    query: AlertListQuery,
) -> tuple[list[AlertEvent], int]:
    """Return (page_rows, total_match_count) for the configured filters.

    Two round-trips on purpose: one ORDER BY + LIMIT for the page, one
    COUNT(*) without LIMIT for the total. Both share the same WHERE clause so
    they always agree.
    """
    base = _apply_filters(
        select(AlertEvent),
        severity=query.severity,
        status=query.status,
        alert_type=query.alert_type,
        lga=query.lga,
        since=query.since,
        until=query.until,
        include_deleted=query.include_deleted,
    )

    page_stmt = (
        base.order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
        .offset(query.offset())
        .limit(query.limit())
    )
    rows = (await session.execute(page_stmt)).scalars().all()

    count_stmt = _apply_filters(
        select(func.count()).select_from(AlertEvent),
        severity=query.severity,
        status=query.status,
        alert_type=query.alert_type,
        lga=query.lga,
        since=query.since,
        until=query.until,
        include_deleted=query.include_deleted,
    )
    total = (await session.execute(count_stmt)).scalar_one()

    return list(rows), int(total)
