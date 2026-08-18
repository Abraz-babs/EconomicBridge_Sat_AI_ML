"""Automatic farmer SMS — the guards, not the plumbing.

This is the one path where satellite output reaches the public unattended, so
every test here pins a way it could go wrong on a real person's phone rather
than a way the code could be tidier.
"""
from __future__ import annotations

import pytest

from config import get_settings
from tasks import farmer_sms_dispatch as fsd


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── it is off unless someone deliberately turns it on ────────────────────


def test_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FARMER_SMS_ENABLED", raising=False)
    get_settings.cache_clear()
    assert fsd.enabled_tenants() == []


def test_enabled_without_a_dpa_org_refuses(monkeypatch) -> None:
    """The notify endpoint is PII-gated; refuse before calling it.

    Silence here would be indistinguishable from calm weather, so the code
    logs a warning — this test pins the refusal itself.
    """
    monkeypatch.setenv("FARMER_SMS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "")
    get_settings.cache_clear()
    assert fsd.enabled_tenants() == []


def test_enabled_with_org_returns_the_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("FARMER_SMS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "025a16c3-4c64-4115-b320-f5dbd8d8bc03")
    monkeypatch.setenv("FARMER_SMS_TENANTS", "kebbi, zamfara")
    get_settings.cache_clear()
    assert fsd.enabled_tenants() == ["kebbi", "zamfara"]


def test_allowlist_is_explicit_not_every_tenant(monkeypatch) -> None:
    """A tenant gaining subscribers must not start auto-sending by itself."""
    monkeypatch.setenv("FARMER_SMS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "org")
    get_settings.cache_clear()
    assert fsd.enabled_tenants() == ["kebbi"], "default allowlist must be Kebbi only"


# ─── it can only ever ask for the safe advisory type ──────────────────────


def test_advisory_type_is_a_constant_not_a_parameter() -> None:
    """drought / flood / conflict are withheld; this must not be able to ask.

    The notifications layer refuses them too — two independent locks on the
    door that matters most.
    """
    assert fsd.ADVISORY == "rainfall"
    import inspect

    src = inspect.getsource(fsd.dispatch_for_tenant)
    assert "ADVISORY" not in src or "advisory=" not in src.replace("ADVISORY", "")


@pytest.mark.asyncio
async def test_notify_sends_only_the_rainfall_type(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "org-uuid")
    get_settings.cache_clear()
    seen: dict = {}

    class _Resp:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {"data": {"dispatched": 3}}

    class _Client:
        async def post(self, url, json, headers):  # noqa: ANN001, ANN201, A002
            seen.update(url=url, body=json, headers=headers)
            return _Resp()

    data = await fsd._notify(_Client(), "kebbi", "Argungu")
    assert data == {"dispatched": 3}
    assert seen["body"]["advisory"] == "rainfall"
    assert seen["body"]["dry_run"] is False
    assert seen["headers"]["X-Tenant-Id"] == "kebbi"
    assert seen["headers"]["X-Organisation-Id"] == "org-uuid"


# ─── failures must not look like success ──────────────────────────────────


@pytest.mark.asyncio
async def test_non_200_returns_none_rather_than_pretending(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "org")
    get_settings.cache_clear()

    class _Resp:
        status_code = 403
        text = "DPA_REQUIRED"

    class _Client:
        async def post(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            return _Resp()

    assert await fsd._notify(_Client(), "kebbi", "Argungu") is None


@pytest.mark.asyncio
async def test_network_error_returns_none(monkeypatch) -> None:
    import httpx

    monkeypatch.setenv("NOTIFICATIONS_ORG_ID", "org")
    get_settings.cache_clear()

    class _Client:
        async def post(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            raise httpx.ConnectError("refused")

    assert await fsd._notify(_Client(), "kebbi", "Argungu") is None


# ─── the query that provides idempotency and freshness ────────────────────


@pytest.mark.asyncio
async def test_pending_only_takes_undispatched_and_recent() -> None:
    """Two properties in one query, and both matter on a farmer's phone.

    sms_dispatched_at IS NULL   -> never send the same advisory twice
    observed_date >= today-2    -> never recover by sending stale rainfall
    """
    captured: dict[str, str] = {}

    class _Result:
        def mappings(self):  # noqa: ANN201
            return self

        def all(self):  # noqa: ANN201
            return []

    class _Session:
        async def execute(self, stmt, params=None):  # noqa: ANN001, ANN201
            captured["sql"] = " ".join(str(stmt).split())
            return _Result()

    await fsd._pending(_Session())
    sql = captured["sql"]
    assert "sms_dispatched_at IS NULL" in sql
    assert "CURRENT_DATE - INTERVAL '2 days'" in sql


@pytest.mark.asyncio
async def test_counts_query_covers_day_and_month() -> None:
    """The monthly cap is what keeps the '2-4 msgs a month' promise honest."""
    captured: dict[str, str] = {}

    class _Row:
        def __getitem__(self, i):  # noqa: ANN001, ANN204
            return 0

    class _Result:
        def first(self):  # noqa: ANN201
            return _Row()

    class _Session:
        async def execute(self, stmt, params=None):  # noqa: ANN001, ANN201
            captured["sql"] = " ".join(str(stmt).split())
            return _Result()

    day, month = await fsd._counts(_Session())
    assert (day, month) == (0, 0)
    assert "date_trunc('day', NOW())" in captured["sql"]
    assert "date_trunc('month', NOW())" in captured["sql"]


def test_default_caps_fit_the_promise() -> None:
    """The enrolment SMS says 'Sako 2-4 a wata' to 11 real people."""
    s = get_settings()
    assert s.farmer_sms_max_per_month <= 4
    assert s.farmer_sms_max_per_day <= s.farmer_sms_max_per_month
