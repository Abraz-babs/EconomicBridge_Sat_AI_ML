"""Historical reports + export for a tenant's alert/encroachment history.

Reads the active tenant's `alert_events` over a date range (months / quarters /
years) and returns either a JSON summary or a CSV download. The session's
search_path is already pinned to tenant_<id> (X-Tenant-Id), and
TenantContextMiddleware enforces that the caller may view that tenant — so these
endpoints are tenant-scoped + access-controlled automatically.

  GET /reports/summary?from=&to=     — aggregated stats for the window
  GET /reports/export.csv?from=&to=  — CSV of the alert rows (opens in Excel)

`from`/`to` are ISO dates (YYYY-MM-DD); both optional (default: last 365 days).
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import SuccessResponse, build_meta
from schemas.reports import ReportSummary

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(from_: str | None, to: str | None) -> tuple[datetime, datetime]:
    """Parse the date window; default to the last 365 days. `to` is inclusive."""
    try:
        end = (datetime.fromisoformat(to) if to else datetime.now(timezone.utc))
        start = (datetime.fromisoformat(from_) if from_
                 else end - timedelta(days=365))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "BAD_DATE",
                                    "message": "from/to must be ISO dates (YYYY-MM-DD)."}) from exc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    # Make `to` inclusive of the whole day.
    if to and len(to) <= 10:
        end = end + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "TENANT_REQUIRED",
                                    "message": "An X-Tenant-Id header is required for reports."})
    return tenant_id


_EXPORT_COLUMNS = [
    "created_at", "alert_type", "severity", "status", "lga", "zone_name",
    "confidence_score", "affected_area_ha", "livelihoods_at_risk",
    "economic_value_ngn", "predicted_breach_hours", "satellite_source",
    "model_name", "model_version",
]


@router.get("/summary", response_model=SuccessResponse[ReportSummary])
async def report_summary(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> SuccessResponse[ReportSummary]:
    tenant_id = _require_tenant(request)
    start, end = _window(from_, to)
    rows = (await session.execute(
        text(
            """
            SELECT severity, status, affected_area_ha, livelihoods_at_risk,
                   economic_value_ngn, model_name
              FROM alert_events
             WHERE COALESCE(is_deleted, false) = false
               AND created_at BETWEEN :start AND :end
            """
        ),
        {"start": start, "end": end},
    )).mappings().all()

    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    ha = liv = 0.0
    ngn = 0.0
    live = 0
    for r in rows:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        ha += r["affected_area_ha"] or 0
        liv += r["livelihoods_at_risk"] or 0
        ngn += r["economic_value_ngn"] or 0
        if r["model_name"] and r["model_name"] != "seed":
            live += 1

    return SuccessResponse(
        data=ReportSummary(
            tenant_id=tenant_id,
            date_from=start.date().isoformat(),
            date_to=end.date().isoformat(),
            total_alerts=len(rows),
            live_alerts=live,
            seed_alerts=len(rows) - live,
            by_severity=by_severity,
            by_status=by_status,
            resolved=by_status.get("resolved", 0),
            affected_area_ha=round(ha, 1),
            livelihoods_at_risk=int(liv),
            economic_value_ngn=round(ngn, 2),
        ),
        meta=build_meta(),
    )


@router.get("/export.csv")
async def report_export_csv(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    tenant_id = _require_tenant(request)
    start, end = _window(from_, to)
    rows = (await session.execute(
        text(
            f"""
            SELECT {', '.join(_EXPORT_COLUMNS)}
              FROM alert_events
             WHERE COALESCE(is_deleted, false) = false
               AND created_at BETWEEN :start AND :end
             ORDER BY created_at DESC
            """  # noqa: S608 — columns are a fixed allowlist, not user input
        ),
        {"start": start, "end": end},
    )).mappings().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_COLUMNS)
    for r in rows:
        writer.writerow([r[c] for c in _EXPORT_COLUMNS])
    buf.seek(0)

    fname = f"{tenant_id}_alerts_{start.date().isoformat()}_{end.date().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
