"""Unit tests for scheduler.py.

We do NOT actually run the AsyncIOScheduler in tests — that involves
real wall-clock timing and asyncio loops, which would make CI flaky.
Instead we verify:

  1. setup_scheduler() registers the expected job(s) with the right cron.
  2. run_daily_firms_ingest() iterates the right tenant list and surfaces
     per-tenant failures without aborting the rest.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from db import PILOT_TENANT_IDS
from scheduler import (
    JOB_ID_FIRMS_DAILY,
    JOB_ID_SHOCKGUARD_DAILY,
    JOB_ID_WORLDPOP_WEEKLY,
    run_daily_firms_ingest,
    setup_scheduler,
)


# ─── setup_scheduler ───────────────────────────────────────────────────────


def test_setup_scheduler_registers_firms_daily_job():
    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_FIRMS_DAILY)
        assert job is not None
        assert "FIRMS" in job.name
        # Cron fires at 06:00 UTC.
        trigger_repr = str(job.trigger)
        assert "hour='6'" in trigger_repr
        assert "minute='0'" in trigger_repr
    finally:
        # Free internal state; we never started it so no shutdown needed.
        sched.remove_all_jobs()


def test_setup_scheduler_registers_worldpop_weekly_job():
    """Slice 09 — Phase B raster sweep. Weekly Sunday 07:00 UTC."""
    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_WORLDPOP_WEEKLY)
        assert job is not None
        assert "WorldPop" in job.name
        trigger_repr = str(job.trigger)
        assert "day_of_week='sun'" in trigger_repr
        assert "hour='7'" in trigger_repr
    finally:
        sched.remove_all_jobs()


def test_setup_scheduler_registers_shockguard_daily_job():
    """ShockGuard flood + drought scan — daily 07:30 UTC. Keeps the
    shock_events feed fresh instead of going stale between on-demand scans."""
    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_SHOCKGUARD_DAILY)
        assert job is not None
        assert "ShockGuard" in job.name
        trigger_repr = str(job.trigger)
        assert "hour='7'" in trigger_repr
        assert "minute='30'" in trigger_repr
    finally:
        sched.remove_all_jobs()


def test_setup_scheduler_uses_utc_timezone():
    sched = setup_scheduler()
    try:
        # APScheduler exposes the scheduler-level timezone, not per job.
        assert str(sched.timezone) == "UTC"
    finally:
        sched.remove_all_jobs()


# ─── run_daily_firms_ingest ────────────────────────────────────────────────


@dataclass
class _FakeAlerts:
    inserted: int = 0


@dataclass
class _FakeIngestResult:
    records_ingested: int
    alerts: _FakeAlerts | None = None


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


class _FakeFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


@pytest.mark.asyncio
async def test_run_daily_firms_ingest_visits_all_pilot_tenants():
    """Default invocation iterates every tenant in PILOT_TENANT_IDS."""
    fake_ingest = AsyncMock(
        side_effect=lambda *_a, **kw: _FakeIngestResult(records_ingested=3)
    )
    with (
        patch("scheduler.get_session_factory", return_value=_FakeFactory()),
        patch("scheduler.ingest_firms_for_tenant", fake_ingest),
    ):
        results = await run_daily_firms_ingest()

    assert set(results) == set(PILOT_TENANT_IDS)
    assert fake_ingest.await_count == len(PILOT_TENANT_IDS)
    assert all(r == 3 for r in results.values())


@pytest.mark.asyncio
async def test_run_daily_firms_ingest_respects_explicit_tenant_subset():
    fake_ingest = AsyncMock(
        side_effect=lambda *_a, **kw: _FakeIngestResult(records_ingested=1)
    )
    with (
        patch("scheduler.get_session_factory", return_value=_FakeFactory()),
        patch("scheduler.ingest_firms_for_tenant", fake_ingest),
    ):
        results = await run_daily_firms_ingest(tenants=["kebbi", "nasarawa"])

    assert sorted(results) == ["kebbi", "nasarawa"]
    assert fake_ingest.await_count == 2


@pytest.mark.asyncio
async def test_run_daily_firms_ingest_continues_after_one_tenant_fails():
    """One tenant's failure must not block the rest."""
    call_order: list[str] = []

    async def fake_ingest(_session, *, tenant_id: str, **_kw):
        call_order.append(tenant_id)
        if tenant_id == "benue":
            raise RuntimeError("simulated FIRMS upstream blip")
        return _FakeIngestResult(records_ingested=2)

    with (
        patch("scheduler.get_session_factory", return_value=_FakeFactory()),
        patch("scheduler.ingest_firms_for_tenant", side_effect=fake_ingest),
    ):
        results = await run_daily_firms_ingest(
            tenants=["kebbi", "benue", "nasarawa"]
        )

    # All three tenants were visited despite the middle one failing.
    assert call_order == ["kebbi", "benue", "nasarawa"]
    assert results["kebbi"] == 2
    assert isinstance(results["benue"], str) and "failed" in results["benue"]
    assert results["nasarawa"] == 2


@pytest.mark.asyncio
async def test_run_daily_firms_ingest_invokes_with_generate_alerts_true():
    """Scheduled runs MUST promote heat detections to alert_events —
    otherwise the dashboard sees no fresh fire alerts overnight."""
    fake_ingest = AsyncMock(
        side_effect=lambda *_a, **kw: _FakeIngestResult(records_ingested=0)
    )
    with (
        patch("scheduler.get_session_factory", return_value=_FakeFactory()),
        patch("scheduler.ingest_firms_for_tenant", fake_ingest),
    ):
        await run_daily_firms_ingest(tenants=["kebbi"])

    _, kwargs = fake_ingest.await_args
    assert kwargs["generate_alerts"] is True
    assert kwargs["trigger"] == "scheduled"
