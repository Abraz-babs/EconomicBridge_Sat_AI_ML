"""Storm scan — the decisions, not the plumbing.

Each test pins something that would mislead a reader of the feed if it broke:
what counts as rated, what a percentile is measured against, and the difference
between "scanned and calm" and "not scanned".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from tasks import storm_scan as ss


def test_region_bounds_come_from_the_daily_feed() -> None:
    """Both feeds must cover the same ground, or they disagree about a place."""
    lon_min, lon_max, lat_min, lat_max = ss._degrees("nigeria")
    # REGIONS["nigeria"] = (1836, 1903, 966, 1031) -> 3.6..10.3E, 6.6..13.1N
    assert lon_min < 3.6 < 10.3 < lon_max
    assert lat_min < 6.6 < 13.1 < lat_max
    # Abuja must be inside — it is the territory that exposed the defect.
    assert lon_min <= 7.49 <= lon_max
    assert lat_min <= 9.06 <= lat_max


def test_thin_history_is_recorded_but_never_rated() -> None:
    """"Highest in 4 days" must not be presentable as "highest in 90"."""
    assert ss._severity(99.9, 99.9, baseline_days=ss.MIN_BASELINE_DAYS - 1) is None


def test_severity_bands_are_relative_to_the_place() -> None:
    n = ss.MIN_BASELINE_DAYS
    assert ss._severity(99.5, None, n) == "critical"
    assert ss._severity(97.5, None, n) == "high"
    assert ss._severity(92.0, None, n) == "medium"
    assert ss._severity(80.0, None, n) is None, "ordinary here is not an alert"


def test_severity_uses_the_worse_of_the_two_windows() -> None:
    """A short violent burst and a long soaking are both worth catching."""
    n = ss.MIN_BASELINE_DAYS
    assert ss._severity(99.5, 40.0, n) == "critical"   # 1h burst
    assert ss._severity(40.0, 99.5, n) == "critical"   # 3h soaking


def test_detector_only_ever_reports_storms() -> None:
    """Naming is load-bearing: this is not a flood claim.

    The Kebbi 2024 backtest scored 0 of 11 on a detector that confused "a
    signal is present" with "a flood happened".
    """
    assert ss.DETECTOR_VERSION == "storm_scan_v1"
    import inspect
    src = inspect.getsource(ss)
    assert "flood_alert" not in src and "flood_detected" not in src


@pytest.mark.asyncio
async def test_percentile_excludes_today() -> None:
    """A storm must never be ranked against itself."""
    captured: dict[str, str] = {}

    class _Row(dict):
        pass

    class _Result:
        def mappings(self):  # noqa: ANN201
            return self

        def first(self):  # noqa: ANN201
            return {"n": 30, "below": 29}

    class _Session:
        async def execute(self, stmt, params=None):  # noqa: ANN001, ANN201
            captured["sql"] = " ".join(str(stmt).split())
            return _Result()

    pct, n = await ss._percentile(
        _Session(), lga="Bwari", column="max_1h_mm", value=12.0)
    assert "day < CURRENT_DATE" in captured["sql"]
    assert (pct, n) == (96.7, 30)


class _FakeSession:
    """Captures what the scan writes, without a database.

    The run-recording path has to be exercised offline: a unit test that
    reaches the developer's Postgres passes here and reds in CI, and worse,
    silently writes rows into a real database.
    """

    #: intensity rows written, shared across every session the factory makes
    intensity: list[dict] = []

    def __init__(self, recorded: list[dict]) -> None:
        self._recorded = recorded
        self.committed = False

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN202
        sql = str(stmt)
        if "ingestion_runs" in sql:
            self._recorded.append(dict(params or {}))
        elif "storm_intensity_daily" in sql and "INSERT" in sql:
            self.intensity.append(dict(params or {}))
        return None

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):  # noqa: ANN202
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN002
        return False


def _fake_factory(recorded: list[dict]):  # noqa: ANN202
    return lambda: _FakeSession(recorded)


@pytest.mark.asyncio
async def test_no_slices_is_reported_as_not_scanned(monkeypatch) -> None:
    """An empty window is not a calm day, and must not read as one."""
    monkeypatch.setattr(ss.ImergHalfHourlyClient, "configured",
                        property(lambda self: True))

    async def _empty(client, http, region, *, end, hours):  # noqa: ANN001, ANN202
        return [], hours * 2

    monkeypatch.setattr(ss, "scan_region", _empty)
    recorded: list[dict] = []
    monkeypatch.setattr(ss, "get_session_factory",
                        lambda: _fake_factory(recorded))
    out = await ss.run_storm_scan(tenants=["fct"])
    assert "not scanned" in out["fct"]

    # And it must be recorded as a FAILED run. A scan that read nothing leaving
    # the same trace as one that read a dry day is how a blind feed goes on
    # reporting "continuously monitored".
    assert len(recorded) == 1
    assert recorded[0]["source"] == "storm_scan_v1"
    assert recorded[0]["status"] == "failed"
    assert recorded[0]["written"] == 0


@pytest.mark.asyncio
async def test_a_scanned_day_stamps_a_successful_run(monkeypatch) -> None:
    """The feed must be visible on the panel even when nothing is rated.

    storm_scan_v1 is listed in the API router's LIVE_SCAN_SOURCES; if the task
    never stamps public.ingestion_runs, the panel shows the feed as never
    having run. That is exactly how the IMERG rainfall advisory shipped, ran
    daily, and stayed invisible for weeks.
    """
    monkeypatch.setattr(ss.ImergHalfHourlyClient, "configured",
                        property(lambda self: True))

    class _Grid:
        at = None

        def sample_max(self, lon, lat):  # noqa: ANN001, ANN202
            return 0.0

    async def _dry(client, http, region, *, end, hours):  # noqa: ANN001, ANN202
        return [_Grid()], hours * 2

    monkeypatch.setattr(ss, "scan_region", _dry)
    monkeypatch.setattr(ss, "select_lgas", lambda tenant, full=False: [])
    recorded: list[dict] = []
    monkeypatch.setattr(ss, "get_session_factory",
                        lambda: _fake_factory(recorded))
    monkeypatch.setattr(ss, "set_tenant_schema",
                        lambda session, tenant: _noop())

    out = await ss.run_storm_scan(tenants=["fct"])
    assert "0 storm event(s)" in out["fct"]
    assert len(recorded) == 1
    assert recorded[0]["status"] == "succeeded"


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_missing_token_skips_rather_than_pretending(monkeypatch) -> None:
    monkeypatch.setattr(ss.ImergHalfHourlyClient, "configured",
                        property(lambda self: False))
    assert await ss.run_storm_scan(tenants=["fct"]) == {}


def test_full_coverage_not_a_rolling_slice() -> None:
    """A half-hourly slice is one request per REGION, so nothing should rotate.

    The 12-day revisit exists because CDSE bills per LGA. This feed does not,
    and sampling a subset here would discard coverage we already paid for.
    """
    import inspect
    src = inspect.getsource(ss.run_storm_scan)
    assert "select_lgas(tenant, full=True)" in src


@pytest.mark.asyncio
async def test_intensity_is_filed_under_the_day_the_rain_fell(monkeypatch) -> None:
    """Not under the day the scan ran.

    The window is 36h so a storm crossing midnight is seen whole, which means
    consecutive runs overlap by twelve hours. Filing everything under "today"
    entered one storm into TWO days of the record - inflating the upper tail
    with a day that never happened, and making every later storm look ordinary
    against it. It also disagreed with the bootstrap, which files by the real
    day, while both fed one distribution.
    """
    monkeypatch.setattr(ss.ImergHalfHourlyClient, "configured",
                        property(lambda self: True))

    # Rain on two distinct UTC days inside one window.
    day_a = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)
    day_b = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)

    class _Grid:
        def __init__(self, at, rate):  # noqa: ANN001
            self.at = at
            self._rate = rate

        def sample_max(self, lon, lat):  # noqa: ANN001, ANN202
            return self._rate

    grids = [
        _Grid(day_a, 20.0), _Grid(day_a + timedelta(minutes=30), 20.0),
        _Grid(day_b, 6.0), _Grid(day_b + timedelta(minutes=30), 6.0),
    ]

    async def _window(client, http, region, *, end, hours):  # noqa: ANN001, ANN202
        return grids, hours * 2

    monkeypatch.setattr(ss, "scan_region", _window)
    monkeypatch.setattr(ss, "select_lgas", lambda tenant, full=False: [
        {"lga": "Bwari", "lon": 7.38, "lat": 9.28},
    ])

    async def _pct(session, *, lga, column, value):  # noqa: ANN001, ANN202
        return None, 0

    monkeypatch.setattr(ss, "_percentile", _pct)
    monkeypatch.setattr(ss, "set_tenant_schema",
                        lambda session, tenant: _noop())

    _FakeSession.intensity = []
    recorded: list[dict] = []
    monkeypatch.setattr(ss, "get_session_factory",
                        lambda: _fake_factory(recorded))

    await ss.run_storm_scan(tenants=["fct"])

    days = {r["day"] for r in _FakeSession.intensity}
    assert days == {date(2026, 8, 30), date(2026, 8, 31)}, (
        "both days of rain must be recorded, each under its own date"
    )

    # And each day carries ITS OWN intensity, not the window's worst.
    by_day = {r["day"]: r for r in _FakeSession.intensity}
    assert by_day[date(2026, 8, 30)]["peak"] > by_day[date(2026, 8, 31)]["peak"]
    assert by_day[date(2026, 8, 31)]["peak"] == pytest.approx(6.0)

    # Coverage is judged against a DAY (48 slices), never the 72-slice window -
    # otherwise every row would look badly under-observed.
    assert all(r["expected"] == 48 for r in _FakeSession.intensity)
