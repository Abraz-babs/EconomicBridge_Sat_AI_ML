"""Forecast check: IMERG grid orientation, LGA weights, scoring, and the job's rules.

No network and no database: IMERG and the session are faked. The grid facts
are IMERG's own (cell i spans [-180 + 0.1 i, -180 + 0.1 (i + 1)), data
lon-major) and were checked against live responses on 2026-11-17.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from processors import rain_check as rc
from tasks import forecast_check as fc


def _square(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


# ─── grid and weights ─────────────────────────────────────────────────────


def test_index_is_a_floor_and_survives_binary_boundaries() -> None:
    """(8.60 + 180) / 0.1 is 1885.999... in floating point; a bare floor puts
    every exact boundary one cell (~11 km) west."""
    li, lj = rc.imerg_index(8.60, 9.576)
    assert (int(li), int(lj)) == (1886, 995)
    li, _ = rc.imerg_index(8.6999, 0.0)
    assert int(li) == 1886


def test_an_lga_inside_one_cell_gets_that_cell_alone() -> None:
    w = rc.imerg_weights(_square(1.0, 1.0, 1.1, 1.1))
    assert w.cells == 1
    assert (int(w.lon[0]), int(w.lat[0])) == (1810, 910)
    assert w.share.tolist() == pytest.approx([1.0])


def test_an_lga_across_two_cells_is_shared_by_area() -> None:
    w = rc.imerg_weights(_square(1.0, 1.0, 1.15, 1.1))       # 0.1 in one cell, 0.05 in the next
    assert w.cells == 2
    assert sorted(w.share.tolist()) == pytest.approx([1 / 3, 2 / 3], abs=0.01)


def test_region_array_keeps_lon_and_lat_on_their_own_axes() -> None:
    """IMERG is lon-major. Swapping the axes reads rain from somewhere else, silently."""
    box = (100, 102, 50, 53)
    rows = {li: [li * 1000 + lj for lj in range(50, 54)] for li in range(100, 103)}
    rows[101][2] = -9999.9                                          # fill
    arr = rc.region_array(rows, box)
    assert arr.values.shape == (3, 4)
    assert arr.values[2, 3] == 102 * 1000 + 53
    assert np.isnan(arr.values[1, 2])


def test_region_rows_may_start_north_of_the_box() -> None:
    arr = rc.region_array({10: [7.0, 8.0]}, (10, 10, 20, 23), rows_lat0=22)
    assert np.isnan(arr.values[0, 1]) and arr.values[0, 2] == 7.0 and arr.values[0, 3] == 8.0


def test_measure_is_the_area_average_with_the_wettest_cell_and_wet_shares() -> None:
    w = rc.CellWeights(lon=np.array([10, 11]), lat=np.array([20, 20]), share=np.array([0.5, 0.5]))
    arr = rc.RegionArray(lon0=10, lat0=20, values=np.array([[0.0], [20.0]], dtype=np.float32))
    m = rc.measure(w, arr)
    assert m.rain_mm == 10.0 and m.rain_max_mm == 20.0
    assert m.wet_share == {1: 0.5, 10: 0.5, 25: 0.0, 50: 0.0}
    assert m.coverage == 1.0


def test_a_cell_without_data_lowers_coverage_and_is_left_out() -> None:
    w = rc.CellWeights(lon=np.array([10, 11]), lat=np.array([20, 20]), share=np.array([0.5, 0.5]))
    arr = rc.RegionArray(lon0=10, lat0=20, values=np.array([[np.nan], [4.0]], dtype=np.float32))
    m = rc.measure(w, arr)
    assert m.coverage == 0.5 and m.rain_mm == 4.0, "a gap is unknown, never 0 mm"


def test_no_data_at_all_is_none_not_a_dry_day() -> None:
    w = rc.CellWeights(lon=np.array([10]), lat=np.array([20]), share=np.array([1.0]))
    arr = rc.RegionArray(lon0=10, lat0=20, values=np.array([[np.nan]], dtype=np.float32))
    assert rc.measure(w, arr) is None


def test_region_box_covers_outlines_not_just_centroids() -> None:
    lon0, lon1, lat0, lat1 = rc.box_for([(1.02, 1.03, 1.47, 1.29)], margin=1)
    assert (lon0, lon1, lat0, lat1) == (1809, 1815, 909, 913)


# ─── scoring ──────────────────────────────────────────────────────────────


D0 = date(2026, 7, 1)


def _measured(values: dict[tuple[str, int], float]) -> list[tuple]:
    return [(lga, D0 + timedelta(days=d), v, 1.0 if v >= 1 else 0.0, 1.0 if v >= 10 else 0.0, 0.0, 0.0)
            for (lga, d), v in values.items()]


def test_each_forecast_lands_on_the_day_it_was_for_at_its_lead() -> None:
    measured = _measured({("A", 0): 0.0, ("A", 1): 5.0, ("A", 3): 0.0})
    ifs = [float(k) for k in range(15)]                      # element k is for D0 - 1 + k
    rec = rc.build_record(measured, [("A", D0 - timedelta(days=1), ifs, None, None, None, None, None)])
    assert rec.days == [D0 + timedelta(days=k) for k in range(4)]
    assert rec.rain["ifs"][0, 0, 1] == 1.0                    # made 1 day before D0
    assert rec.rain["ifs"][0, 1, 2] == 2.0                    # made 2 days before D0 + 1
    assert np.isnan(rec.rain["ifs"][0, 0, 0]), "no run from D0 itself was given"
    assert np.isnan(rec.obs[0, 2]), "an unmeasured day is a gap, not a dry day"
    assert np.isnan(rec.rain["aifs"]).all(), "a missing model stays missing"


def test_counts_are_hits_false_alarms_misses_and_correct_dry() -> None:
    f = np.array([5.0, 5.0, 0.0, 0.0, np.nan])
    o = np.array([3.0, 0.0, 8.0, 0.2, 9.0])
    a, b, c, d, sf, so, err, wet, *_ = rc.counts(f, o)
    assert (a, b, c, d) == (1, 1, 1, 1)
    assert sf == 10.0 and so == pytest.approx(11.2)
    assert wet == 3 and err == pytest.approx(2.0 + 5.0 + 8.0)


def test_soaking_days_are_counted_beside_wet_days() -> None:
    """Calling 1 mm everywhere catches every wet day; it must not pass for
    catching the soaking ones."""
    f = np.array([12.0, 12.0, 2.0, 0.0])
    o = np.array([15.0, 3.0, 20.0, 0.0])
    assert rc.counts(f, o)[8:] == [1, 1, 1, 1]


def test_the_summary_carries_counts_by_model_and_lead() -> None:
    measured = _measured({("A", d): (6.0 if d % 2 else 0.0) for d in range(6)})
    runs = [("A", D0 + timedelta(days=r), [6.0, 0.0] * 7 + [6.0], [0.0] * 15,
             [80] * 10, [20] * 10, [0] * 10, [0] * 10) for r in range(6)]
    s = rc.summarise_record(rc.build_record(measured, runs), recent_days=3, ribbon_days=4)
    assert s["days_checked"] == 6 and s["lga_days"] == 6
    assert len(s["scorecard"]["all"]["ifs"]) == rc.LEADS
    a, b, c, d = s["scorecard"]["all"]["aifs"][0][:4]
    assert (a, b, c, d) == (0, 0, 3, 3), "an always-dry model misses every wet day"
    assert len(s["ribbon"]) == 4 and s["ribbon"][-1]["day"] == "2026-07-06"
    assert len(s["lgas"][0]["ifs"]) == len(rc.SHOWN_LEADS)
    assert s["pairs"] > 0


def test_chances_are_checked_against_the_share_that_got_the_rain() -> None:
    measured = _measured({("A", 0): 12.0})
    run = ("A", D0, [12.0] * 15, None, [80] * 10, [80] * 10, [0] * 10, [0] * 10)
    s = rc.summarise_record(rc.build_record(measured, [run]))
    bins = s["chances"]["10"]["bins"]["0-2"]
    assert bins[4] == [1, 80.0, 1.0], "80% lands in the 70-90 bin, against a share of 1.0"
    n, brier, base = s["chances"]["10"]["brier"][0]
    assert n == 1 and brier == pytest.approx(0.04)


# ─── the job ──────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, rows: list | None = None, scalar: object | None = None) -> None:
        self._rows, self._scalar = rows or [], scalar

    def __iter__(self):  # noqa: ANN204
        return iter(self._rows)

    def all(self) -> list:
        return self._rows

    def scalar(self) -> object | None:
        return self._scalar


class _Session:
    def __init__(self, log: list[dict]) -> None:
        self._log = log

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN202
        sql = str(stmt)
        if "ingestion_runs" in sql:
            self._log.append(dict(params or {}))
        return _Result()

    async def commit(self) -> None:
        return None

    async def __aenter__(self):  # noqa: ANN202
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN002
        return False


async def _noop(*_a, **_k) -> None:  # noqa: ANN002, ANN003
    return None


@pytest.mark.asyncio
async def test_no_token_is_a_recorded_failure_not_a_quiet_day(monkeypatch) -> None:
    recorded: list[dict] = []

    class _NoToken:
        configured = False

        def close(self) -> None:
            return None

    monkeypatch.setattr(fc, "GpmImergClient", _NoToken)
    monkeypatch.setattr(fc, "get_session_factory", lambda: (lambda: _Session(recorded)))
    monkeypatch.setattr(fc, "set_tenant_schema", _noop)
    out = await fc.run_forecast_check(tenants=["kebbi"], today=date(2026, 11, 18))
    assert out["kebbi"].startswith("failed")
    assert recorded[0]["source"] == "forecast_check_v1" and recorded[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_days_already_held_are_not_fetched_again(monkeypatch) -> None:
    asked: list[date] = []

    class _Client:
        async def region_grid(self, *, lon0, lon1, lat0, lat1, day):  # noqa: ANN001, ANN202
            asked.append(day)
            return None                                         # "not published yet"

    async def _held(session, start, end):  # noqa: ANN001, ANN202
        return {date(2026, 11, 16)}

    monkeypatch.setattr(fc, "get_session_factory", lambda: (lambda: _Session([])))
    monkeypatch.setattr(fc, "set_tenant_schema", _noop)
    monkeypatch.setattr(fc, "_days_held", _held)
    days = [date(2026, 11, 16), date(2026, 11, 15)]
    added, notes = await fc.measure_days(_Client(), days, ["ghana"])
    assert asked == [date(2026, 11, 15)] and added == {"ghana": 0} and notes == []


def test_the_backfill_never_reaches_the_live_feed() -> None:
    from scripts.backfill_forecast_check import runs_to_fetch

    runs = runs_to_fetch(date(2026, 5, 1), None, date(2026, 11, 17), date(2026, 11, 18))
    assert runs[0] == date(2026, 5, 1) and runs[-1] == date(2026, 11, 16)
    assert runs_to_fetch(date(2026, 5, 1), date(2026, 5, 3), None, date(2026, 11, 18))[-1] == date(2026, 5, 3)
    assert runs_to_fetch(date(2026, 11, 17), None, date(2026, 11, 17), date(2026, 11, 18)) == []


def test_nothing_here_deletes_a_record() -> None:
    """Standing rule: no record may go."""
    import inspect

    import scripts.backfill_forecast_check as bf

    for mod in (fc, rc, bf):
        src = inspect.getsource(mod).upper()
        assert "DELETE FROM" not in src and "TRUNCATE" not in src


def test_the_job_runs_twice_a_day_and_can_be_run_by_hand() -> None:
    from routers.jobs import _TRIGGERABLE_JOBS
    from scheduler import JOB_ID_FORECAST_CHECK_DAILY, setup_scheduler

    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_FORECAST_CHECK_DAILY)
        assert job is not None and "Forecast check" in job.name
        trigger = str(job.trigger)
        assert "hour='10,22'" in trigger and "minute='30'" in trigger
    finally:
        sched.remove_all_jobs()
    assert _TRIGGERABLE_JOBS[JOB_ID_FORECAST_CHECK_DAILY] is fc.run_forecast_check
