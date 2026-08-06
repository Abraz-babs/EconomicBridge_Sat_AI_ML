"""Super-admin account activity — who is using the platform, and how.

Read-only counterpart to admin_tenants.py: that router provisions accounts,
this one shows what they did afterwards. Both are gated by `require_super_admin`
(role `super_admin`), so a tenant or partner account gets 403 here — a partner
can see its own data but never the roster of other accounts.

Backed by `services/activity.py`; see that module for why usage lives in a
rollup table rather than in `public.audit_log`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from dependencies import CurrentUser, require_super_admin
from schemas.activity import (
    AccountActivityData,
    AccountDetailData,
    AccountSummary,
    DailyPoint,
    LoginEvent,
    NamedCount,
)
from schemas.envelope import ResponseMeta, SuccessResponse

router = APIRouter(tags=["admin-activity"])

# Trailing window the panel defaults to. Long enough that a monthly-cadence
# government user still shows as active, short enough to reflect current use.
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365


def _meta() -> ResponseMeta:
    return ResponseMeta(tenant_id=None, trace_id=uuid4(),
                        timestamp=datetime.now(timezone.utc))


@router.get("/admin/activity", response_model=SuccessResponse[AccountActivityData])
async def account_activity(
    request: Request,
    # Auth is declared before the session on purpose: FastAPI resolves
    # dependencies in signature order, so an unauthorised caller is rejected
    # without ever opening a database connection.
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=MAX_WINDOW_DAYS)] = DEFAULT_WINDOW_DAYS,
) -> SuccessResponse[AccountActivityData]:
    """Every account with its usage over the trailing window, busiest first.

    Accounts with no activity are included (as zeroes) on purpose — an invited
    account that has never signed in is exactly what an operator needs to see.
    """
    from services.activity import account_summary, flush

    # Flush first so the panel reflects the last few seconds rather than the
    # last flush tick. Only this API task's buffer, but that is enough to make
    # "log in, then check the panel" behave the way an operator expects.
    await flush()

    rows = await account_summary(session, days=days)
    return SuccessResponse(
        data=AccountActivityData(
            window_days=days,
            accounts=[
                AccountSummary(
                    user_id=r["user_id"], email=r["email"],
                    full_name=r["full_name"], role=r["role"],
                    is_active=r["is_active"], org_name=r["org_name"],
                    org_slug=r["org_slug"], last_login_at=r["last_login_at"],
                    last_seen=r["last_seen"], requests=int(r["requests"] or 0),
                    active_days=int(r["active_days"] or 0),
                    logins=int(r["logins"] or 0),
                    modules=list(r["modules"] or []),
                    tenants=list(r["tenants"] or []),
                )
                for r in rows
            ],
        ),
        meta=_meta(),
    )


@router.get("/admin/activity/{user_id}",
            response_model=SuccessResponse[AccountDetailData])
async def account_activity_detail(
    user_id: UUID,
    request: Request,
    # Auth is declared before the session on purpose: FastAPI resolves
    # dependencies in signature order, so an unauthorised caller is rejected
    # without ever opening a database connection.
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=MAX_WINDOW_DAYS)] = DEFAULT_WINDOW_DAYS,
) -> SuccessResponse[AccountDetailData]:
    """One account's daily series, module/tenant split, and recent sign-ins."""
    from services.activity import account_detail, flush

    await flush()
    d = await account_detail(session, user_id=user_id, days=days)
    return SuccessResponse(
        data=AccountDetailData(
            window_days=days,
            daily=[DailyPoint(day=r["day"], requests=int(r["requests"]))
                   for r in d["daily"]],
            by_module=[NamedCount(name=r["module"] or "other",
                                  requests=int(r["requests"]))
                       for r in d["by_module"]],
            by_tenant=[NamedCount(name=r["tenant_id"] or "none",
                                  requests=int(r["requests"]))
                       for r in d["by_tenant"]],
            logins=[LoginEvent(at=r["at"], ip_address=r["ip_address"],
                               user_agent=r["user_agent"])
                    for r in d["logins"]],
        ),
        meta=_meta(),
    )
