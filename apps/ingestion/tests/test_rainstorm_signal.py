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

from processors.rainstorm_signal import (
    EXTREME_MM,
    HEAVY_MM,
    compute_rainstorm,
)
from sources.gpm_imerg import (
    GpmImergClient,
    ImergAuthError,
    _lat_index,
    _lon_index,
    _parse_ascii,
)


# ─── compute_rainstorm ────────────────────────────────────────────────────


def _dry_season(n: int = 20) -> list[float]:
    """Mostly-dry baseline with a few drizzle days."""
    return [0.0] * (n - 4) + [0.4, 1.2, 0.8, 2.0]


def _wet_season(n: int = 20) -> list[float]:
    """A genuinely wet Middle-Belt baseline: ~12 mm on wet days."""
    return [0.0, 14.0, 9.0, 11.0, 0.0, 16.0, 12.0, 8.0, 13.0, 10.0] * (n // 10)


def test_ordinary_wet_day_is_not_flagged() -> None:
    """15 mm in a wet season is a normal day, not a rainstorm."""
    assert compute_rainstorm([*_wet_season(), 15.0]) is None


def test_drizzle_spike_in_dry_season_is_not_flagged() -> None:
    """The relative anomaly is enormous (6 mm vs a ~1 mm baseline) but nobody's
    roof comes off — the absolute gate must reject it. This is the case a plain
    z-score gets wrong."""
    assert compute_rainstorm([*_dry_season(), 6.0]) is None


def test_extreme_day_against_wet_baseline_is_flagged() -> None:
    sig = compute_rainstorm([*_wet_season(), 120.0])
    assert sig is not None
    assert sig.rain_mm == 120.0
    assert sig.severity == "critical"
    assert sig.confidence_band == "HIGH"
    assert sig.baseline_mm > 0
    assert sig.ratio > 2.0


def test_heavy_day_is_medium_not_critical() -> None:
    sig = compute_rainstorm([*_wet_season(), HEAVY_MM + 1.0])
    assert sig is not None
    assert sig.severity == "medium"


def test_heavy_rain_in_an_already_soaked_climate_needs_the_ratio() -> None:
    """A place where 40 mm days are routine should not alarm at 55 mm."""
    soaked = [40.0, 45.0, 38.0, 42.0, 44.0, 39.0, 41.0, 43.0] * 3
    assert compute_rainstorm([*soaked, 55.0]) is None


def test_thin_baseline_requires_the_extreme_bar() -> None:
    """With too few wet days to judge 'unusual', only a truly extreme total
    qualifies — and it is reported with reduced confidence."""
    thin = [0.0] * 18 + [2.0, 3.0]           # 2 wet days, below MIN_WET_DAYS
    assert compute_rainstorm([*thin, HEAVY_MM + 5]) is None
    sig = compute_rainstorm([*thin, EXTREME_MM + 5])
    assert sig is not None
    assert sig.confidence_band in ("MEDIUM", "LOW")


def test_returns_none_without_enough_history() -> None:
    assert compute_rainstorm([80.0]) is None


def test_metrics_disclose_the_resolution_limit() -> None:
    """The payload must say IMERG is hazard-level, not damage-level — this text
    is what stops an operator reading a pin as 'this village was destroyed'."""
    sig = compute_rainstorm([*_wet_season(), 130.0])
    assert sig is not None
    m = sig.as_metrics()
    assert "not a damage assessment" in str(m["interpretation"])
    assert m["instrument"].startswith("GPM IMERG")


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


def test_parse_ascii_extracts_only_data_values() -> None:
    body = (
        "Dataset {\n} 3B-DAY-L;\n"
        "---------------------------------------------\n"
        "precipitation[0][1885][994], 61.2, 3.4\n"
        "precipitation[0][1886][994], 118.7, 0.0\n"
    )
    assert _parse_ascii(body) == [61.2, 3.4, 118.7, 0.0]


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
