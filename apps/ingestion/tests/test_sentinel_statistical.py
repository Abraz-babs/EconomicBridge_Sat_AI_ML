"""Unit tests for sources/sentinel_statistical.py.

Mocks every network call (CLAUDE.md §11). What we pin:

  * `configured` reflects the parent CopernicusClient's auth state.
  * No auth → `compute_time_series` returns [] without making a call.
  * Real Statistical API response shape → StatPoint fields populated.
  * Non-200 from Statistical raises CopernicusError.
  * S1 request body pins acquisitionMode/polarization/resolution.
  * S2 request body honours max_cloud_cover_pct.
  * Date validation: start >= end raises ValueError.
  * NaN means → mean=None (Statistical API emits NaN for fully-masked intervals).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

import sources.sentinel_statistical as ss
from config import get_settings
from sources.copernicus import CopernicusClient, CopernicusError
from sources.sentinel_statistical import (
    EVALSCRIPT_S1_VV_DB,
    EVALSCRIPT_S2_NDVI,
    SentinelStatisticalClient,
    StatPoint,
    _build_request_body,
    _first_of_next_month,
    _parse_iso,
    _parse_response,
    _QUOTA_EXHAUSTED_CODE,
    _quota_breaker_open,
    _retry_after_seconds,
    _trip_quota_breaker,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _stat_payload(points: int = 3, *, with_nan: bool = False) -> dict[str, Any]:
    rows = []
    base_dt = datetime(2026, 4, 1, tzinfo=timezone.utc)
    from datetime import timedelta
    for i in range(points):
        mean_val = float("nan") if with_nan and i == 1 else -11.5 + i * 0.3
        rows.append({
            "interval": {
                "from": (base_dt + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to":   (base_dt + timedelta(days=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "outputs": {
                "default": {
                    "bands": {
                        "B0": {
                            "stats": {
                                "min": mean_val - 0.5,
                                "max": mean_val + 0.5,
                                "mean": mean_val,
                                "stDev": 0.2,
                                "sampleCount": 12500,
                            }
                        }
                    }
                }
            }
        })
    return {"data": rows, "status": "OK"}


def _route_token_then_stat(stat_response: dict | None, *, stat_status: int = 200):
    """Route OAuth token request, then statistical API request."""
    state = {"token_calls": 0, "stat_calls": 0, "last_stat_body": None}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            state["token_calls"] += 1
            return httpx.Response(200, content=json.dumps({
                "access_token": "fake-token",
                "expires_in": 1800,
                "token_type": "Bearer",
            }).encode())
        if "/statistics" in url:
            state["stat_calls"] += 1
            state["last_stat_body"] = json.loads(request.content.decode())
            if stat_status == 200:
                return httpx.Response(200, content=json.dumps(stat_response or {}).encode())
            return httpx.Response(stat_status, content=b"error")
        return httpx.Response(404, content=b"no route")

    return httpx.MockTransport(handler), state


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "cid")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Configuration ────────────────────────────────────────────────────────


def test_configured_mirrors_parent_client(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        client = SentinelStatisticalClient(CopernicusClient())
        assert client.configured is False
    finally:
        get_settings.cache_clear()


def test_configured_true_when_creds_present(configured):
    client = SentinelStatisticalClient(CopernicusClient())
    assert client.configured is True


# ─── compute_time_series ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_empty_when_unconfigured(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        copernicus = CopernicusClient(http=httpx.AsyncClient())
        client = SentinelStatisticalClient(copernicus)
        out = await client.compute_time_series(
            bbox=(3.6, 10.8, 5.5, 13.2),
            start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end=datetime(2026, 4, 30, tzinfo=timezone.utc),
            dataset="sentinel-1-grd",
            evalscript=EVALSCRIPT_S1_VV_DB,
        )
        assert out == []
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_returns_stat_points_for_real_response(configured):
    transport, state = _route_token_then_stat(_stat_payload(points=3))
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)
    out = await client.compute_time_series(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-1-grd",
        evalscript=EVALSCRIPT_S1_VV_DB,
    )
    assert state["token_calls"] == 1
    assert state["stat_calls"] == 1
    assert len(out) == 3
    p0 = out[0]
    assert isinstance(p0, StatPoint)
    assert p0.dataset == "sentinel-1-grd"
    assert p0.band_name == "default"
    assert p0.mean == pytest.approx(-11.5)
    assert p0.std_dev == pytest.approx(0.2)
    assert p0.sample_count == 12500
    # Points sorted by interval_from ascending.
    assert out[0].interval_from < out[1].interval_from < out[2].interval_from


@pytest.mark.asyncio
async def test_nan_mean_becomes_none(configured):
    transport, _ = _route_token_then_stat(_stat_payload(points=3, with_nan=True))
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)
    out = await client.compute_time_series(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-2-l2a",
        evalscript=EVALSCRIPT_S2_NDVI,
    )
    means = [p.mean for p in out]
    assert means[1] is None    # fully-masked interval
    assert means[0] is not None and means[2] is not None


@pytest.mark.asyncio
async def test_raises_on_5xx(configured):
    transport, _ = _route_token_then_stat(None, stat_status=503)
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=transport))
    client = SentinelStatisticalClient(copernicus)
    with pytest.raises(CopernicusError, match="503"):
        await client.compute_time_series(
            bbox=(3.6, 10.8, 5.5, 13.2),
            start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end=datetime(2026, 4, 30, tzinfo=timezone.utc),
            dataset="sentinel-1-grd",
            evalscript=EVALSCRIPT_S1_VV_DB,
        )


@pytest.mark.asyncio
async def test_validates_date_order(configured):
    copernicus = CopernicusClient(http=httpx.AsyncClient())
    client = SentinelStatisticalClient(copernicus)
    with pytest.raises(ValueError, match="earlier"):
        await client.compute_time_series(
            bbox=(3.6, 10.8, 5.5, 13.2),
            start=datetime(2026, 4, 30, tzinfo=timezone.utc),
            end=datetime(2026, 4, 1, tzinfo=timezone.utc),
            dataset="sentinel-1-grd",
            evalscript=EVALSCRIPT_S1_VV_DB,
        )


# ─── Request body shape ───────────────────────────────────────────────────


def test_s1_body_pins_acquisition_mode_and_polarization():
    """SAR data filter must specify IW + DV + HIGH so the Statistical API
    doesn't mix Strip-Map with IW. This is a SUBTLE bug source on CDSE."""
    body = _build_request_body(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-1-grd",
        evalscript=EVALSCRIPT_S1_VV_DB,
        agg_interval="P1D",
        max_cloud_cover_pct=None,
    )
    data_filter = body["input"]["data"][0]["dataFilter"]
    assert data_filter["acquisitionMode"] == "IW"
    assert data_filter["polarization"] == "DV"
    assert data_filter["resolution"] == "HIGH"


def test_s2_body_honours_cloud_cover_filter():
    body = _build_request_body(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-2-l2a",
        evalscript=EVALSCRIPT_S2_NDVI,
        agg_interval="P1D",
        max_cloud_cover_pct=20.0,
    )
    data_filter = body["input"]["data"][0]["dataFilter"]
    assert data_filter["maxCloudCoverage"] == 20.0


def test_bbox_and_crs_in_request():
    body = _build_request_body(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-2-l2a",
        evalscript=EVALSCRIPT_S2_NDVI,
        agg_interval="P1D",
        max_cloud_cover_pct=None,
    )
    assert body["input"]["bounds"]["bbox"] == [3.6, 10.8, 5.5, 13.2]
    assert "EPSG/0/4326" in body["input"]["bounds"]["properties"]["crs"]


def test_agg_interval_is_threaded_through():
    body = _build_request_body(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-2-l2a",
        evalscript=EVALSCRIPT_S2_NDVI,
        agg_interval="P5D",
        max_cloud_cover_pct=None,
    )
    assert body["aggregation"]["aggregationInterval"]["of"] == "P5D"


# ─── Parser edge cases ────────────────────────────────────────────────────


def test_parser_handles_empty_data():
    points = _parse_response({"data": []}, dataset="sentinel-1-grd")
    assert points == []


def test_parser_skips_malformed_rows():
    payload = {"data": [
        "not a dict",
        {"interval": {"from": "bad"}},          # bad iso date
        # Valid row sandwiched between malformed
        {
            "interval": {"from": "2026-04-01T00:00:00Z", "to": "2026-04-02T00:00:00Z"},
            "outputs": {"default": {"bands": {"B0": {"stats": {"mean": -10.5, "sampleCount": 100}}}}}
        },
    ]}
    points = _parse_response(payload, dataset="sentinel-1-grd")
    assert len(points) == 1
    assert points[0].mean == -10.5


def test_iso_parser_round_trips_with_z():
    dt = _parse_iso("2026-04-15T12:34:56Z")
    assert dt.year == 2026 and dt.month == 4 and dt.day == 15
    assert dt.tzinfo is not None


# ─── Monthly-quota circuit breaker + 429 retry ─────────────────────────────
# Guards the CDSE free-tier PU budget (see 31c3a54): on a 403
# ACCESS_INSUFFICIENT_PROCESSING_UNITS we trip a process-global breaker and
# skip all Statistical calls until the 1st of next month; 429s are retried
# with Retry-After-aware backoff. The breaker is module-global, so every test
# that touches it resets the state via `reset_breaker` to avoid bleeding into
# the response-shape tests above.


@pytest.fixture
def reset_breaker():
    ss._quota_blocked_until = None
    yield
    ss._quota_blocked_until = None


def test_first_of_next_month_rolls_within_year():
    nxt = _first_of_next_month(datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc))
    assert (nxt.year, nxt.month, nxt.day) == (2026, 8, 1)
    assert nxt.tzinfo is timezone.utc


def test_first_of_next_month_rolls_over_december():
    nxt = _first_of_next_month(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert (nxt.year, nxt.month, nxt.day) == (2027, 1, 1)


def test_breaker_closed_by_default(reset_breaker):
    assert _quota_breaker_open(datetime(2026, 7, 25, tzinfo=timezone.utc)) is False


def test_breaker_opens_then_auto_resets_after_rollover(reset_breaker):
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    until = _trip_quota_breaker(now)
    assert until == datetime(2026, 8, 1, tzinfo=timezone.utc)
    # Inside the blocked window the breaker reads open.
    assert _quota_breaker_open(datetime(2026, 7, 26, tzinfo=timezone.utc)) is True
    # Once the 1st arrives it auto-closes and clears the stored date.
    assert _quota_breaker_open(datetime(2026, 8, 1, tzinfo=timezone.utc)) is False
    assert ss._quota_blocked_until is None


@pytest.mark.parametrize("header,attempt,expected", [
    ("5", 0, 5.0),               # honour Retry-After
    ("999", 0, 30.0),            # capped at _MAX_BACKOFF_SECONDS
    ("not-a-number", 3, 8.0),    # unparseable header -> 2**attempt
    (None, 4, 16.0),             # no header -> exponential backoff
    (None, 10, 30.0),            # backoff capped
])
def test_retry_after_seconds(header, attempt, expected):
    assert _retry_after_seconds(header, attempt) == expected


@pytest.mark.asyncio
async def test_quota_403_trips_breaker_and_returns_empty(configured, reset_breaker):
    """A 403 ACCESS_INSUFFICIENT_PROCESSING_UNITS yields [] (not an error) and
    arms the breaker so subsequent calls short-circuit until month roll-over."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, content=json.dumps({
                "access_token": "t", "expires_in": 1800, "token_type": "Bearer",
            }).encode())
        return httpx.Response(403, content=f"quota spent: {_QUOTA_EXHAUSTED_CODE}".encode())

    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client = SentinelStatisticalClient(copernicus)
    out = await client.compute_time_series(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-1-grd",
        evalscript=EVALSCRIPT_S1_VV_DB,
    )
    assert out == []
    assert ss._quota_blocked_until is not None


@pytest.mark.asyncio
async def test_open_breaker_short_circuits_without_calling(configured, reset_breaker):
    """While the breaker is open, no HTTP call is made — not even a token fetch."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, content=b"should never be reached")

    ss._quota_blocked_until = _first_of_next_month(datetime.now(timezone.utc))
    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client = SentinelStatisticalClient(copernicus)
    out = await client.compute_time_series(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-1-grd",
        evalscript=EVALSCRIPT_S1_VV_DB,
    )
    assert out == []
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_429_is_retried_then_succeeds(configured, reset_breaker, monkeypatch):
    """A 429 is retried (backoff slept out) and the following 200 is parsed."""
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(ss.asyncio, "sleep", _no_sleep)
    state = {"stat_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "openid-connect/token" in str(request.url):
            return httpx.Response(200, content=json.dumps({
                "access_token": "t", "expires_in": 1800, "token_type": "Bearer",
            }).encode())
        state["stat_calls"] += 1
        if state["stat_calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, content=b"slow down")
        return httpx.Response(200, content=json.dumps(_stat_payload(points=2)).encode())

    copernicus = CopernicusClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client = SentinelStatisticalClient(copernicus)
    out = await client.compute_time_series(
        bbox=(3.6, 10.8, 5.5, 13.2),
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        dataset="sentinel-1-grd",
        evalscript=EVALSCRIPT_S1_VV_DB,
    )
    assert state["stat_calls"] == 2   # one retry
    assert len(out) == 2
