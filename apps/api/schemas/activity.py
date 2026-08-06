"""Response models for the super-admin account-activity panel."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class AccountSummary(BaseModel):
    """One account's usage over the requested window."""

    user_id: UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    org_name: str | None
    org_slug: str | None
    # Set by the login handler even before any activity is counted, so an
    # account that signed in once and left still has a truthful "last seen".
    last_login_at: datetime | None
    last_seen: datetime | None
    requests: int
    active_days: int
    logins: int
    modules: list[str]
    tenants: list[str]


class AccountActivityData(BaseModel):
    window_days: int
    accounts: list[AccountSummary]


class DailyPoint(BaseModel):
    day: date
    requests: int


class NamedCount(BaseModel):
    name: str
    requests: int


class LoginEvent(BaseModel):
    at: datetime
    ip_address: str | None
    user_agent: str | None


class AccountDetailData(BaseModel):
    window_days: int
    daily: list[DailyPoint]
    by_module: list[NamedCount]
    by_tenant: list[NamedCount]
    logins: list[LoginEvent]
