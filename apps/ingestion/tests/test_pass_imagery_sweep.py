"""Unit tests for tasks/pass_imagery_sweep.py.

We never hit N2YO or CDSE. Both clients are stubbed.

What we pin:
  * A pass within ±PASS_WINDOW_MIN of `now` triggers a CDSE refresh.
  * A pass far in the future is skipped and reports minutes_to_pass.
  * No passes at all → skipped with "no-pass-in-window".
  * N2YO error on one (tenant, sat) doesn't abort the rest.
  * CDSE error after a positive N2YO answer is captured per-pair.
  * Sentinel-1 maps to sentinel-1-grd; Sentinel-2 → sentinel-2-l2a.
  * Refresh count + skipped count agree with the decision list.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.imagery_recent import (
    RecentImageryResult,
    clear_cache as _clear_recent_cache,
)
from sources.copernicus import CopernicusError
from sources.n2yo import N2yoError, SatellitePass
from tasks import pass_imagery_sweep as sweep_module
from tasks.pass_imagery_sweep import (
    EO_SATELLITES,
    PASS_WINDOW_MIN,
    run_pass_imagery_sweep,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


NOW = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_cache():
    _clear_recent_cache()
    yield
    _clear_recent_cache()


def _pass(
    *,
    satellite: str,
    norad_id: int,
    group: str,
    minutes_from_now: int,
    lat: float = 12.0,
    lon: float = 4.5,
) -> SatellitePass:
    start = NOW + timedelta(minutes=minutes_from_now)
    return SatellitePass(
        satellite_name=satellite,
        satellite_group=group,
        norad_id=norad_id,
        observer_lat=lat,
        observer_lon=lon,
        start_utc=start,
        max_utc=start + timedelta(minutes=5),
        end_utc=start + timedelta(minutes=10),
        start_elevation_deg=0.0,
        max_elevation_deg=45.0,
        end_elevation_deg=0.0,
        max_azimuth_deg=90.0,
        max_azimuth_compass="E",
        duration_seconds=600,
    )


class _FakeN2yo:
    """Stub that returns whatever passes the test wired in for each
    (satellite_key, observer_lat) combo. Defaults to empty list."""

    def __init__(self, plan: dict[str, list[SatellitePass]] | None = None,
                 raise_for: set[str] | None = None) -> None:
        self.plan = plan or {}
        self.raise_for = raise_for or set()
        self.calls: list[tuple[str, float, float]] = []

    async def fetch_passes(
        self,
        *,
        satellite_key: str,
        observer_lat: float,
        observer_lon: float,
        days: int = 1,
        min_elevation: int | None = None,
    ) -> list[SatellitePass]:
        self.calls.append((satellite_key, observer_lat, observer_lon))
        if satellite_key in self.raise_for:
            raise N2yoError(f"simulated upstream blip for {satellite_key}")
        return list(self.plan.get(satellite_key, []))


class _FakeImageryService:
    """Captures get_recent_imagery calls so we can count refreshes."""

    def __init__(self, *, raise_for: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.raise_for = raise_for or set()

    async def __call__(
        self,
        *,
        tenant_id: str,
        collection: str,
        days: int = 14,
        max_cloud_cover: float | None = None,
        limit: int = 10,
        client=None,
    ) -> RecentImageryResult:
        self.calls.append((tenant_id, collection))
        if collection in self.raise_for:
            raise CopernicusError(f"simulated CDSE error for {collection}")
        return RecentImageryResult(
            tenant_id=tenant_id,
            collection=collection,
            days=days,
            bbox=(0.0, 0.0, 1.0, 1.0),
            max_cloud_cover_pct=max_cloud_cover,
            scenes=(),
        )


# ─── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pass_inside_window_triggers_refresh(monkeypatch):
    plan = {
        # Sentinel-2A passes in 5 min — well inside the ±20 min window.
        "SENTINEL-2A": [_pass(
            satellite="SENTINEL-2A", norad_id=40697, group="S2",
            minutes_from_now=5,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )

    # One refresh for Sentinel-2A → sentinel-2-l2a.
    refreshed = [d for d in result.decisions if d.refreshed]
    assert len(refreshed) == 1
    assert refreshed[0].satellite == "SENTINEL-2A"
    assert refreshed[0].collection == "sentinel-2-l2a"
    assert refreshed[0].minutes_to_pass == 5
    assert ("kebbi", "sentinel-2-l2a") in fake_get.calls


@pytest.mark.asyncio
async def test_pass_outside_window_is_skipped(monkeypatch):
    plan = {
        # Pass is 4 hours away — well outside ±20 min window.
        "SENTINEL-1A": [_pass(
            satellite="SENTINEL-1A", norad_id=39634, group="S1",
            minutes_from_now=240,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )

    s1_decisions = [d for d in result.decisions if d.satellite == "SENTINEL-1A"]
    assert len(s1_decisions) == 1
    d = s1_decisions[0]
    assert d.refreshed is False
    assert d.skipped_reason == "no-pass-in-window"
    assert d.minutes_to_pass == 240
    # And no imagery refresh fired for S1.
    assert ("kebbi", "sentinel-1-grd") not in fake_get.calls


@pytest.mark.asyncio
async def test_no_passes_at_all_reports_minutes_to_pass_none(monkeypatch):
    n2yo = _FakeN2yo(plan={})
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )

    for d in result.decisions:
        assert d.refreshed is False
        assert d.skipped_reason == "no-pass-in-window"
        assert d.minutes_to_pass is None
    assert fake_get.calls == []


@pytest.mark.asyncio
async def test_n2yo_error_on_one_sat_does_not_abort_rest(monkeypatch):
    plan = {
        "SENTINEL-2B": [_pass(
            satellite="SENTINEL-2B", norad_id=42063, group="S2",
            minutes_from_now=2,
        )],
    }
    n2yo = _FakeN2yo(plan=plan, raise_for={"SENTINEL-1A"})
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )

    by_sat = {d.satellite: d for d in result.decisions}
    # S1A errored → its decision captures the failure
    assert by_sat["SENTINEL-1A"].refreshed is False
    assert by_sat["SENTINEL-1A"].skipped_reason == "n2yo-error"
    assert "simulated" in (by_sat["SENTINEL-1A"].error or "")
    # S2B still ran and refreshed
    assert by_sat["SENTINEL-2B"].refreshed is True


@pytest.mark.asyncio
async def test_cdse_error_after_pass_match_is_captured_not_raised(monkeypatch):
    plan = {
        "SENTINEL-2A": [_pass(
            satellite="SENTINEL-2A", norad_id=40697, group="S2",
            minutes_from_now=10,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService(raise_for={"sentinel-2-l2a"})
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )

    s2a = next(d for d in result.decisions if d.satellite == "SENTINEL-2A")
    assert s2a.refreshed is False
    assert s2a.skipped_reason == "cdse-error"
    assert "simulated CDSE error" in (s2a.error or "")


@pytest.mark.asyncio
async def test_sweep_covers_every_eo_satellite_for_every_tenant(monkeypatch):
    """Default tenant list × EO_SATELLITES = total decisions."""
    n2yo = _FakeN2yo(plan={})
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi", "benue"], n2yo=n2yo, now=NOW,
    )

    assert len(result.decisions) == 2 * len(EO_SATELLITES)
    # And every (tenant, satellite) is unique.
    pairs = {(d.tenant_id, d.satellite) for d in result.decisions}
    assert len(pairs) == 2 * len(EO_SATELLITES)


@pytest.mark.asyncio
async def test_refreshed_count_and_skipped_count_sum_to_total(monkeypatch):
    plan = {
        # Only S2A is in-window; everything else is empty.
        "SENTINEL-2A": [_pass(
            satellite="SENTINEL-2A", norad_id=40697, group="S2",
            minutes_from_now=PASS_WINDOW_MIN - 1,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )
    assert result.refreshed_count + result.skipped_count == len(result.decisions)
    assert result.refreshed_count == 1


@pytest.mark.asyncio
async def test_pass_exactly_at_window_edge_is_included(monkeypatch):
    plan = {
        "SENTINEL-2A": [_pass(
            satellite="SENTINEL-2A", norad_id=40697, group="S2",
            minutes_from_now=PASS_WINDOW_MIN,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )
    s2a = next(d for d in result.decisions if d.satellite == "SENTINEL-2A")
    assert s2a.refreshed is True


@pytest.mark.asyncio
async def test_unknown_tenant_is_silently_skipped(monkeypatch):
    n2yo = _FakeN2yo(plan={})
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["atlantis"], n2yo=n2yo, now=NOW,
    )
    # No decisions because no PILOT_BBOX entry.
    assert result.decisions == []
    assert n2yo.calls == []


@pytest.mark.asyncio
async def test_sweep_uses_sentinel_1_collection_for_s1_pass(monkeypatch):
    plan = {
        "SENTINEL-1A": [_pass(
            satellite="SENTINEL-1A", norad_id=39634, group="S1",
            minutes_from_now=3,
        )],
    }
    n2yo = _FakeN2yo(plan=plan)
    fake_get = _FakeImageryService()
    monkeypatch.setattr(sweep_module, "get_recent_imagery", fake_get)

    result = await run_pass_imagery_sweep(
        tenants=["kebbi"], n2yo=n2yo, now=NOW,
    )
    s1 = next(d for d in result.decisions if d.satellite == "SENTINEL-1A")
    assert s1.refreshed is True
    assert s1.collection == "sentinel-1-grd"
    assert ("kebbi", "sentinel-1-grd") in fake_get.calls


# ─── Scheduler integration ────────────────────────────────────────────────


def test_setup_scheduler_registers_pass_imagery_sweep_job():
    from scheduler import (
        JOB_ID_PASS_IMAGERY_SWEEP,
        setup_scheduler,
    )

    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_PASS_IMAGERY_SWEEP)
        assert job is not None
        # IntervalTrigger repr — every 15 min.
        assert "interval" in str(type(job.trigger)).lower()
        assert "0:15:00" in str(job.trigger)
    finally:
        sched.remove_all_jobs()
