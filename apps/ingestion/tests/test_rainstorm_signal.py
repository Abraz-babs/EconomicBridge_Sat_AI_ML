"""Unit tests for processors/rainstorm_signal.py + sources/gpm_imerg.py.

Every network call is mocked (CLAUDE.md §11). What these pin:

  * the two gates — absolute damaging-rain AND relative-to-baseline — since
    either alone produces nonsense (a plain z-score alarms on drizzle in the
    dry season; a plain threshold alarms all season in the Middle Belt);
  * the wet-day baseline, which is the whole reason the relative gate works;
  * IMERG's (time, lon, lat) dim order, the one silent-wrong-answer bug;
  * that a GES DISC 401 is reported as APPLICATION AUTHORISATION rather than
    an expired token — the two are indistinguishable from the status code and
    we lost time to exactly that confusion.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from processors.rainstorm_signal import compute_rainstorm
from sources.gpm_imerg import (
    GpmImergClient,
    ImergAuthError,
    RegionGrid,
    _lat_index,
    _lon_index,
    _parse_ascii,
    _parse_region_ascii,
)


# ─── compute_rainstorm ────────────────────────────────────────────────────
# Calibrated and validated on real IMERG (245 days/LGA, 2026-07-26). The
# numbers below are taken from that fetch, not invented, so the tests fail if
# anyone re-tunes the detector away from measured climatology.


# Mokwa's REAL wet-day distribution, sampled every other day from the 245-day
# IMERG fetch of 2026-07-26 (median 6.4 mm, p99 47.5 mm). Using measured data
# rather than an invented curve is the point: a hand-made distribution is what
# let the first version's thresholds look reasonable while being unusable.
MOKWA_WET_DAYS = [
    1.0, 1.0, 1.1, 1.1, 1.3, 1.4, 1.5, 1.6, 1.8, 1.9, 2.0, 2.0,
    2.4, 3.0, 3.3, 3.4, 3.6, 3.7, 4.0, 4.1, 4.3, 4.9, 5.0, 5.4,
    5.8, 5.9, 6.0, 6.1, 6.7, 6.9, 7.2, 7.2, 8.4, 8.6, 8.7, 9.3,
    10.2, 10.6, 10.8, 11.4, 12.6, 13.2, 13.5, 14.3, 14.7, 16.3, 17.6, 18.3,
    18.4, 19.1, 20.5, 21.8, 28.0, 32.4, 34.5, 43.6,
]


def _mokwa_like() -> list[float]:
    """Real Mokwa climatology: the measured wet days plus its ~54% dry days."""
    return [*([0.0] * 66), *MOKWA_WET_DAYS]


def test_ordinary_wet_day_is_not_flagged() -> None:
    assert compute_rainstorm([*_mokwa_like(), 12.0]) is None


def test_mokwa_disaster_day_is_correctly_NOT_flagged() -> None:
    """THE key regression. Mokwa 2025-05-29 killed 151 people, and its 26.1 mm
    ranked p93 in Mokwa's own distribution — wet, not exceptional. Catching it
    needs the p90 mark, which flags ~6% of all LGA-days (~4,100 alerts/season
    nationally). We accept the miss rather than ship that noise; the flood came
    from a failed railway embankment, not from the rain.

    If this test starts failing, someone has lowered the threshold to chase a
    past event. Read the module docstring before changing it."""
    assert compute_rainstorm([*_mokwa_like(), 26.14]) is None


def test_genuinely_exceptional_day_is_flagged() -> None:
    """Well past the LGA's p99 (47.5 mm) — the case this detector exists for.
    75 mm is 1.58x that, which lands 'high'; severity is a ratio to the LGA's
    own p99, not an absolute millimetre band."""
    sig = compute_rainstorm([*_mokwa_like(), 75.0])
    assert sig is not None
    assert sig.rain_mm == 75.0
    assert sig.percentile >= 99.0
    assert sig.severity in ("high", "critical")


def test_far_past_p99_reads_critical() -> None:
    sig = compute_rainstorm([*_mokwa_like(), 110.0])   # 2.3x Mokwa's p99
    assert sig is not None
    assert sig.severity == "critical"


def test_severity_scales_with_exceedance_of_the_lgas_own_p99() -> None:
    mild = compute_rainstorm([*_mokwa_like(), 21.0])
    big = compute_rainstorm([*_mokwa_like(), 90.0])
    assert big is not None and big.severity == "critical"
    if mild is not None:
        assert mild.severity in ("medium", "high")


def test_absolute_floor_guards_the_arid_case() -> None:
    """In a very dry LGA even the p99 wet day can be small. 8 mm is not a flood
    risk anywhere, however unusual it is locally."""
    arid = ([0.0] * 8 + [1.5, 2.0, 1.2, 3.0]) * 10
    assert compute_rainstorm([*arid, 8.0]) is None


def test_thin_history_returns_none_rather_than_guessing() -> None:
    assert compute_rainstorm([*([0.0] * 40 + [5.0] * 5), 60.0]) is None


def test_returns_none_without_enough_history() -> None:
    assert compute_rainstorm([80.0]) is None


def test_metrics_state_this_is_not_rainstorm_detection() -> None:
    """The payload must not let a reader infer we detect wind damage — that
    claim is exactly what validation disproved."""
    sig = compute_rainstorm([*_mokwa_like(), 80.0])
    assert sig is not None
    text = str(sig.as_metrics()["interpretation"])
    assert "NOT a rainstorm detection" in text
    assert "not a damage assessment" in text


# ─── grid indexing ────────────────────────────────────────────────────────


def test_grid_indices_match_imerg_layout() -> None:
    """0.1° grid, lon -180..180 (3600), lat -90..90 (1800)."""
    assert _lon_index(-180.0) == 0
    assert _lat_index(-90.0) == 0
    assert _lon_index(0.0) == 1800
    assert _lat_index(0.0) == 900
    # Riyom, Plateau — verified against the live DMR on 2026-07-26.
    assert _lon_index(8.691) == 1886
    assert _lat_index(9.576) == 995


def test_grid_indices_are_clamped_not_wrapped() -> None:
    assert _lon_index(400.0) == 3599
    assert _lat_index(-400.0) == 0


# ─── ascii parsing ────────────────────────────────────────────────────────


def test_parse_ascii_ignores_the_coordinate_array() -> None:
    """Verbatim shape of a live GES DISC response (captured 2026-07-26).

    The `precipitation.lat` row is comma-separated exactly like the data rows.
    Parsing it as data folds latitudes (~9.5) into the series as phantom ~9 mm
    readings — silently wrong, never an error. Data rows carry bracketed
    indices; coordinate rows do not.
    """
    body = (
        "Dataset: 3B-DAY-L.MS.MRG.3IMERG.20260602-S000000-E235959.V07C.nc4\n"
        "precipitation.lat, 9.45000000000001, 9.55, 9.65000000000001\n"
        "precipitation.precipitation[precipitation.time=16949]"
        "[precipitation.lon=8.55], 3.285, 3.45, 3.915\n"
        "precipitation.precipitation[precipitation.time=16949]"
        "[precipitation.lon=8.65], 9.465, 3.965, 5.885\n"
    )
    out = _parse_ascii(body)
    assert out == [3.285, 3.45, 3.915, 9.465, 3.965, 5.885]
    assert 9.55 not in out          # the latitude, not a rainfall value


# ─── client behaviour ─────────────────────────────────────────────────────


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
    from config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_401_is_reported_as_app_authorisation_not_expiry(token) -> None:
    """A GES DISC 401 with a token that works elsewhere means the account has
    not approved 'NASA GESDISC DATA ARCHIVE'. The message must say so."""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, content=b"Unauthorized")
    )
    client = GpmImergClient(http=httpx.AsyncClient(transport=transport))
    with pytest.raises(ImergAuthError, match="AUTHORISATION"):
        await client.daily_rain(8.691, 9.576, date(2026, 6, 2))


@pytest.mark.asyncio
async def test_missing_granule_returns_none_not_zero(token) -> None:
    """The Late run lags ~1 day. An absent granule is 'unknown', never 0 mm —
    zero-filling would drag baselines down and manufacture anomalies."""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(404, content=b"not found")
    )
    client = GpmImergClient(http=httpx.AsyncClient(transport=transport))
    assert await client.daily_rain(8.691, 9.576, date(2026, 6, 2)) is None


@pytest.mark.asyncio
async def test_fill_values_are_dropped(token) -> None:
    body = "precipitation[0][1885][994], -9999.9, 12.5, -9999.9\n"
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=body.encode())
    )
    client = GpmImergClient(http=httpx.AsyncClient(transport=transport))
    row = await client.daily_rain(8.691, 9.576, date(2026, 6, 2))
    assert row is not None
    assert row.cells == 1
    assert row.max_mm == 12.5


@pytest.mark.asyncio
async def test_window_summary_uses_max_for_convective_cells(token) -> None:
    """A storm can sit beside the centroid and still have hit the LGA, so the
    trigger is the window max while the mean stays available for context."""
    body = "precipitation[0][1885][994], 2.0, 4.0, 96.0\n"
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=body.encode())
    )
    client = GpmImergClient(http=httpx.AsyncClient(transport=transport))
    row = await client.daily_rain(8.691, 9.576, date(2026, 6, 2))
    assert row is not None
    assert row.max_mm == 96.0
    assert row.mean_mm == 34.0


@pytest.mark.asyncio
async def test_unconfigured_client_is_inert(token, monkeypatch) -> None:
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    from config import get_settings
    get_settings.cache_clear()
    client = GpmImergClient()
    assert client.configured is False
    assert await client.daily_rain(8.691, 9.576, date(2026, 6, 2)) is None


# ─── rainstorm_scan task ──────────────────────────────────────────────────
# The SQL here is never executed by CI (no Postgres), so these pin the shapes
# that would only otherwise fail in production: real ingestion_runs column
# names, and the auth-abort contract.


def test_run_audit_uses_real_ingestion_runs_columns() -> None:
    """migration 0004 defines records_ingested / error_message / dry_run.
    Writing records_written / error would raise UndefinedColumn at runtime and
    only surface on a live sweep."""
    import inspect

    from tasks import rainstorm_scan

    src = inspect.getsource(rainstorm_scan._record_run)
    # Look at the INSERT column list only — the docstring deliberately names
    # the wrong-but-tempting columns as a warning, so a whole-source substring
    # check would match its own comment.
    cols = src.split("INSERT INTO public.ingestion_runs (", 1)[1].split(")", 1)[0]
    assert "records_ingested" in cols
    assert "error_message" in cols
    assert "dry_run" in cols
    assert "records_written" not in cols


def test_insert_writes_flood_not_rainstorm() -> None:
    """Validation proved daily rainfall cannot see wind-damage storms, so these
    rows must NOT claim to be rainstorms. Exceptional rainfall is a flood
    precursor; labelling it 'rainstorm' would repeat the mislabelling this whole
    change set removed. Stays human-review flagged: modelled, not observed."""
    import inspect

    from tasks import rainstorm_scan

    sql = inspect.getsource(rainstorm_scan._insert)
    assert "'flood'" in sql
    assert "'rainstorm'" not in sql
    assert "TRUE" in sql          # requires_human_review


def test_scan_replaces_prior_rows_of_its_own_source_only() -> None:
    """Idempotent per run, and must never touch historical_v1 or the CDSE
    scan's rows."""
    import inspect

    from tasks import rainstorm_scan

    sql = inspect.getsource(rainstorm_scan._replace_prior)
    assert "source = :s" in sql
    assert rainstorm_scan.SOURCE == "rainstorm_scan_v1"


@pytest.mark.asyncio
async def test_run_is_inert_without_a_token(monkeypatch) -> None:
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    from config import get_settings

    get_settings.cache_clear()
    from tasks import rainstorm_scan

    assert await rainstorm_scan.run() == {}
    get_settings.cache_clear()


# ─── region grid (the fetch strategy that makes this a feed) ──────────────
# Per-LGA fetching cost 447 x 90 ~ 40,000 requests/run. One region grid per day
# covers every LGA in it, so 3 requests/day serve all 447. These pin the parsing
# and the index arithmetic that makes that safe.


def test_region_parse_indexes_rows_by_their_own_longitude() -> None:
    """Each data row labels its longitude in DEGREES. We read that back rather
    than assuming rows arrive in index order — a reordered or partial response
    would otherwise shift every LGA's rainfall onto its neighbour, silently."""
    body = (
        "Dataset: 3B-DAY-L.MS.MRG.3IMERG.20260602-...nc4\n"
        "precipitation.lat, 9.45, 9.55, 9.65\n"
        "precipitation.precipitation[precipitation.time=1][precipitation.lon=8.65],"
        " 1.0, 2.0, 3.0\n"
        "precipitation.precipitation[precipitation.time=1][precipitation.lon=8.55],"
        " 4.0, 5.0, 6.0\n"
    )
    rows = _parse_region_ascii(body)
    # 8.65 -> cell 1886, 8.55 -> cell 1885, regardless of the order they arrived
    assert rows[_lon_index(8.65)] == [1.0, 2.0, 3.0]
    assert rows[_lon_index(8.55)] == [4.0, 5.0, 6.0]
    assert len(rows) == 2                      # the lat coordinate row excluded


def test_lon_index_maps_a_point_into_its_containing_cell() -> None:
    """Verified against a live response 2026-07-26: requesting index 1886 returns
    centre 8.65, and cell 1886 spans [8.60, 8.70). Riyom's 8.691 must therefore
    map to 1886. Using round() instead of floor lands on 1887 — one cell (~11 km)
    east, which is wrong but produces perfectly plausible-looking numbers."""
    assert _lon_index(8.691) == 1886
    # Exact cell boundaries: (8.60+180)/0.1 is 1885.9999999999998 in binary
    # floating point, so this is the regression for the epsilon in _lon_index.
    assert _lon_index(8.60) == 1886
    assert _lon_index(8.59) == 1885
    assert _lat_index(9.50) == 995


def test_region_grid_samples_the_same_3x3_window_as_a_point_fetch() -> None:
    grid = RegionGrid(
        day=date(2026, 6, 2),
        lat0=994,
        rows={1885: [1.0, 2.0, 3.0], 1886: [4.0, 99.0, 6.0], 1887: [7.0, 8.0, 9.0]},
    )
    got = grid.sample(8.691, 9.576)            # -> lon 1886, lat 995
    assert got is not None
    assert got.cells == 9
    assert got.max_mm == 99.0


def test_region_grid_drops_fill_values() -> None:
    grid = RegionGrid(
        day=date(2026, 6, 2), lat0=994,
        rows={1886: [-9999.9, 12.5, -9999.9]},
    )
    got = grid.sample(8.691, 9.576)
    assert got is not None
    assert got.cells == 1 and got.max_mm == 12.5


def test_every_pilot_tenant_is_mapped_to_a_region() -> None:
    """An unmapped tenant silently gets no grids and therefore no advisories —
    it would look like 'no rain' forever rather than erroring."""
    from db import PILOT_TENANT_IDS
    from tasks.rainstorm_scan import REGIONS, TENANT_REGION

    for tenant in PILOT_TENANT_IDS:
        assert tenant in TENANT_REGION, f"{tenant} has no IMERG region"
        assert TENANT_REGION[tenant] in REGIONS


def test_rainfall_job_is_registered_and_does_not_clash_with_shockguard() -> None:
    import inspect

    from scheduler import (
        JOB_ID_RAINFALL_DAILY,
        JOB_ID_SHOCKGUARD_DAILY,
        setup_scheduler,
    )

    src = inspect.getsource(setup_scheduler)
    assert "run_rainfall_scan" in src
    assert JOB_ID_RAINFALL_DAILY != JOB_ID_SHOCKGUARD_DAILY


def test_insert_leaves_unquantified_measures_null_not_zero() -> None:
    """A rainfall advisory does not estimate onset hours, area or population.
    Writing 0 would render "~0 at risk over 0 km2 · onset in 0h" — a false
    statement of no risk, not an absence of data. Migration 0037 makes the
    columns nullable so NULL is expressible; this pins that we use it."""
    import inspect

    from tasks import rainstorm_scan

    sql = inspect.getsource(rainstorm_scan._insert)
    assert "NULL, NULL, NULL" in sql
