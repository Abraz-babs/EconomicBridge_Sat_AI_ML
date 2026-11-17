"""ECMWF open-data forecast: grid orientation, LGA weights, daily totals, run handling.

No network: every ECMWF call is faked. The grid facts tested here were read off
the live feed on 2026-11-17 (first longitude 180 = -180, first latitude 90,
IFS rain in metres accumulated from step 0).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pytest

from processors import forecast_lga as fl
from sources import ecmwf_opendata as eo
from tasks import ecmwf_forecast as ef


def _square(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


# ─── grid orientation ─────────────────────────────────────────────────────


def test_run_url_matches_the_published_layout() -> None:
    run = eo.Run(date(2026, 11, 17), 0)
    assert run.url(eo.IFS, 24) == (
        "https://data.ecmwf.int/forecasts/20261117/00z/ifs/0p25/oper/20261117000000-24h-oper-fc.grib2")
    assert run.url(eo.ENS_CHANCES, 240).endswith("/ifs/0p25/enfo/20261117000000-240h-enfo-ep.grib2")
    assert run.url(eo.AIFS, 360).endswith("/aifs-single/0p25/oper/20261117000000-360h-oper-fc.grib2")
    assert run.base_time == datetime(2026, 11, 17, tzinfo=timezone.utc)


def test_domain_crop_reads_the_right_place() -> None:
    """Column 0 is -180 and row 0 is 90 N. Getting either backwards reads a
    plausible number from the wrong hemisphere, silently."""
    rows, cols = np.mgrid[0:eo.NJ, 0:eo.NI]
    lat = eo.FIRST_LAT - rows * eo.RES
    lon = -180.0 + cols * eo.RES
    grid = lat * 1000 + lon            # encodes the cell centre in its value
    dom = eo.Domain.around(3.5, 10.5, 5.5, 13.5)     # around Kebbi
    part = dom.crop(grid)
    r, c = int(round((dom.lat0 - 12.5) / eo.RES)), int(round((4.25 - dom.lon0) / eo.RES))
    assert part[r, c] == pytest.approx(12.5 * 1000 + 4.25)
    assert dom.lat0 >= 13.5 and dom.lon0 <= 3.5


def test_decode_refuses_a_grid_it_does_not_expect() -> None:
    eccodes = pytest.importorskip("eccodes")
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        message = eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)
    with pytest.raises(eo.EcmwfOpenDataError, match="unexpected grid"):
        eo.decode(message)


# ─── LGA weights ──────────────────────────────────────────────────────────


DOM = eo.Domain.around(0.0, 0.0, 2.0, 2.0)


def test_an_lga_filling_one_cell_gets_that_cell_alone() -> None:
    w = fl.area_weights(_square(0.875, 0.875, 1.125, 1.125), DOM)
    assert w.cells == 1
    assert w.share.tolist() == pytest.approx([1.0])
    assert DOM.lat0 - w.rows[0] * eo.RES == pytest.approx(1.0)
    assert DOM.lon0 + w.cols[0] * eo.RES == pytest.approx(1.0)


def test_an_lga_split_across_two_cells_is_shared_by_area() -> None:
    # Three quarters in the cell centred on lon 1.0, one quarter in lon 1.25.
    w = fl.area_weights(_square(0.875, 0.875, 1.25, 1.125), DOM)
    assert w.cells == 2
    shares = sorted(w.share.tolist())
    assert shares[0] == pytest.approx(1 / 3, abs=0.02)
    assert shares[1] == pytest.approx(2 / 3, abs=0.02)


def test_a_hole_is_not_counted_as_part_of_the_lga() -> None:
    outer = [[0.375, 0.375], [1.625, 0.375], [1.625, 1.625], [0.375, 1.625], [0.375, 0.375]]
    hole = [[0.875, 0.875], [1.125, 0.875], [1.125, 1.125], [0.875, 1.125], [0.875, 0.875]]
    w = fl.area_weights({"type": "Polygon", "coordinates": [outer, hole]}, DOM)
    centre = [(r, c) for r, c in zip(w.rows, w.cols, strict=True)
              if DOM.lat0 - r * eo.RES == pytest.approx(1.0) and DOM.lon0 + c * eo.RES == pytest.approx(1.0)]
    assert not centre, "the cell inside the hole must carry no weight"


def test_an_lga_smaller_than_the_lattice_still_gets_its_cell() -> None:
    w = fl.area_weights(_square(1.0, 1.0, 1.001, 1.001), DOM)
    assert w.cells == 1


@pytest.mark.asyncio
async def test_fields_are_cut_down_as_they_arrive(monkeypatch) -> None:
    """The ensemble file is 40 global fields of ~8 MB; held whole, four runs in
    flight killed the 1 GB backfill task (2026-11-17). Each field is cropped
    the moment it is decoded."""
    client = eo.EcmwfOpenDataClient(None)
    sizes: list[tuple[int, int]] = []

    async def _index(url):  # noqa: ANN001, ANN202
        return [{"param": "tpg1", "_offset": 0, "_length": 3}, {"param": "tpg10", "_offset": 3, "_length": 3}]

    class _Resp:
        content = b"abc"

    async def _get(url, byte_range=None):  # noqa: ANN001, ANN202
        return _Resp()

    def _keep(grid: np.ndarray) -> np.ndarray:
        sizes.append(grid.shape)
        return DOM.crop(grid)

    monkeypatch.setattr(client, "index", _index)
    monkeypatch.setattr(client, "_get", _get)
    monkeypatch.setattr(eo, "decode", lambda payload: np.zeros((eo.NJ, eo.NI)))
    got = await client.fields("x.grib2", lambda e: True, keep=_keep)
    assert sizes == [(eo.NJ, eo.NI)] * 2
    assert [g.shape for _, g in got] == [DOM.shape, DOM.shape]


def test_an_outline_outside_the_domain_is_an_error() -> None:
    with pytest.raises(ValueError, match="outside"):
        fl.area_weights(_square(10.0, 10.0, 10.5, 10.5), DOM)


# ─── daily totals and summaries ───────────────────────────────────────────


def test_daily_totals_difference_the_accumulation_and_never_go_negative() -> None:
    acc = [np.array([[0.001]]), np.array([[0.003]]), np.array([[0.003]]), np.array([[0.0029]])]
    days = fl.daily_totals(acc, scale=1000.0)       # IFS rain is in metres
    assert [round(float(d[0, 0]), 3) for d in days] == [1.0, 2.0, 0.0, 0.0]


def _fields(aifs: bool = True, chances: bool = True) -> fl.ForecastFields:
    shape = DOM.shape
    rain = [np.full(shape, 2.04, dtype=np.float32) for _ in range(ef.DAYS)]
    return fl.ForecastFields(
        rain_ifs=rain,
        rain_aifs=[np.full(shape, 1.0, dtype=np.float32) for _ in range(ef.DAYS)] if aifs else None,
        chances={t: [np.full(shape, 33.4, dtype=np.float32)] * ef.CHANCE_DAYS
                 for t in ef.CHANCE_THRESHOLDS} if chances else None,
        temp_dawn=[np.full(shape, 21.06, dtype=np.float32)] * ef.TEMP_DAYS,
        temp_afternoon=[np.full(shape, 35.94, dtype=np.float32)] * ef.TEMP_DAYS,
    )


def test_summary_rounds_and_keeps_every_product() -> None:
    w = fl.area_weights(_square(0.875, 0.875, 1.125, 1.125), DOM)
    s = fl.summarise("Augie", w, _fields())
    assert s.rain_ifs_mm[0] == 2.0 and len(s.rain_ifs_mm) == ef.DAYS
    assert s.rain_ifs_max_mm[0] == 2.0
    assert s.chance is not None and s.chance[10][0] == 33
    assert s.temp_dawn_c == [21.1] * ef.TEMP_DAYS and s.temp_afternoon_c[0] == 35.9


def test_a_missing_product_stays_missing() -> None:
    """Never borrow the physics model's rain for the AI model, or invent chances."""
    w = fl.area_weights(_square(0.875, 0.875, 1.125, 1.125), DOM)
    s = fl.summarise("Augie", w, _fields(aifs=False, chances=False))
    assert s.rain_aifs_mm is None
    assert s.chance is None


def test_cell_window_covers_the_tenant_with_a_margin() -> None:
    win = fl.window_for(DOM, (0.5, 0.5, 1.0, 1.0), margin=1)
    assert win.lat0 == pytest.approx(1.25) and win.lon0 == pytest.approx(0.25)
    assert (win.n_rows, win.n_cols) == (5, 5)
    assert len(win.take(np.zeros(DOM.shape))) == 25


# ─── run selection and partial runs ───────────────────────────────────────


class _FakeClient:
    def __init__(self, published: dict[tuple[date, str], bool]) -> None:
        self._published = published

    async def published(self, run: eo.Run, product: tuple[str, str, str]) -> bool:
        name = {eo.IFS: "ifs", eo.AIFS: "aifs", eo.ENS_CHANCES: "ens"}[product]
        return self._published.get((run.day, name), False)


@pytest.mark.asyncio
async def test_the_newest_complete_run_wins() -> None:
    today, yesterday = date(2026, 11, 17), date(2026, 11, 16)
    fake = _FakeClient({(today, "ifs"): True, (today, "aifs"): True, (today, "ens"): True,
                        (yesterday, "ifs"): True})
    run, have = await eo.EcmwfOpenDataClient.latest_run(fake, datetime(2026, 11, 17, 9, 15, tzinfo=timezone.utc))
    assert run.day == today and have == {"ifs", "aifs", "ens"}


@pytest.mark.asyncio
async def test_a_physics_only_run_is_used_when_nothing_complete_exists() -> None:
    today = date(2026, 11, 17)
    fake = _FakeClient({(today, "ifs"): True})
    run, have = await eo.EcmwfOpenDataClient.latest_run(fake, datetime(2026, 11, 17, 9, 15, tzinfo=timezone.utc))
    assert run.day == today and have == {"ifs"}


@pytest.mark.asyncio
async def test_nothing_published_is_none_not_an_old_forecast() -> None:
    fake = _FakeClient({})
    assert await eo.EcmwfOpenDataClient.latest_run(fake, datetime(2026, 11, 17, 9, tzinfo=timezone.utc)) is None


@pytest.mark.asyncio
async def test_a_failing_ai_model_degrades_to_missing_and_says_so(monkeypatch) -> None:
    async def _one(client, run, product, step, param, domain):  # noqa: ANN001, ANN202
        if product == eo.AIFS:
            raise eo.EcmwfOpenDataError("AIFS 503")
        return np.zeros(domain.shape, dtype=np.float32)

    async def _chances(client, run, domain):  # noqa: ANN001, ANN202
        return {t: [np.zeros(domain.shape)] * ef.CHANCE_DAYS for t in ef.CHANCE_THRESHOLDS}

    monkeypatch.setattr(ef, "_one", _one)
    monkeypatch.setattr(ef, "_chances", _chances)
    fields, problems = await ef.fetch_fields(None, eo.Run(date(2026, 11, 17)), {"ifs", "aifs", "ens"}, DOM)
    assert fields.rain_aifs is None
    assert fields.chances is not None
    assert any("aifs failed" in p for p in problems)


# ─── run records ──────────────────────────────────────────────────────────


class _Result:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def first(self) -> object | None:
        return self._row


class _FakeSession:
    def __init__(self, recorded: list[dict], stored: bool) -> None:
        self._recorded, self._stored = recorded, stored
        self.inserts: list[str] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN202
        sql = str(stmt)
        if "ingestion_runs" in sql:
            self._recorded.append(dict(params or {}))
        elif sql.lstrip().startswith("SELECT 1 FROM ecmwf_forecast"):
            return _Result((1,) if self._stored else None)
        elif "INSERT" in sql:
            self.inserts.append(sql)
        return _Result(None)

    async def commit(self) -> None:
        return None

    async def __aenter__(self):  # noqa: ANN202
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN002
        return False


async def _noop(*_a, **_k) -> None:  # noqa: ANN002, ANN003
    return None


@pytest.mark.asyncio
async def test_no_published_run_is_recorded_as_a_failure(monkeypatch) -> None:
    """A feed that reads nothing must not leave the trace of a quiet day."""
    async def _none(self, now, lookback_days=2):  # noqa: ANN001, ANN202
        return None

    recorded: list[dict] = []
    monkeypatch.setattr(eo.EcmwfOpenDataClient, "latest_run", _none)
    monkeypatch.setattr(ef, "get_session_factory", lambda: (lambda: _FakeSession(recorded, False)))
    monkeypatch.setattr(ef, "set_tenant_schema", _noop)
    out = await ef.run_ecmwf_forecast(tenants=["kebbi"])
    assert out["kebbi"].startswith("failed")
    assert recorded[0]["source"] == "ecmwf_forecast_v1" and recorded[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_an_already_stored_run_is_a_success_without_rewriting(monkeypatch) -> None:
    async def _found(self, now, lookback_days=2):  # noqa: ANN001, ANN202
        return eo.Run(date(2026, 11, 17)), {"ifs", "aifs", "ens"}

    async def _fetch(client, run, have, domain):  # noqa: ANN001, ANN202
        return _fields(), []

    recorded: list[dict] = []
    session = _FakeSession(recorded, stored=True)
    monkeypatch.setattr(eo.EcmwfOpenDataClient, "latest_run", _found)
    monkeypatch.setattr(ef, "fetch_fields", _fetch)
    monkeypatch.setattr(ef, "get_session_factory", lambda: (lambda: session))
    monkeypatch.setattr(ef, "set_tenant_schema", _noop)
    out = await ef.run_ecmwf_forecast(tenants=["kebbi"])
    assert "already stored" in out["kebbi"]
    assert recorded[0]["status"] == "succeeded" and recorded[0]["error"] is None
    assert not session.inserts


def test_the_task_never_deletes_a_forecast() -> None:
    """Every run is kept (standing rule: no record may go)."""
    import inspect

    src = inspect.getsource(ef).upper()
    assert "DELETE FROM" not in src and "TRUNCATE" not in src


def test_the_job_runs_after_the_00_utc_run_is_published() -> None:
    from scheduler import JOB_ID_ECMWF_FORECAST_DAILY, setup_scheduler

    sched = setup_scheduler()
    try:
        job = sched.get_job(JOB_ID_ECMWF_FORECAST_DAILY)
        assert job is not None and "ECMWF" in job.name
        trigger = str(job.trigger)
        assert "hour='9,13'" in trigger and "minute='15'" in trigger
    finally:
        sched.remove_all_jobs()


def test_the_job_can_be_run_by_hand() -> None:
    from routers.jobs import _TRIGGERABLE_JOBS
    from scheduler import JOB_ID_ECMWF_FORECAST_DAILY

    assert _TRIGGERABLE_JOBS[JOB_ID_ECMWF_FORECAST_DAILY] is ef.run_ecmwf_forecast
