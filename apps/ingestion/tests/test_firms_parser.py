"""Unit tests for the FIRMS CSV parser + mock client.

These do NOT hit the network or the database. Default `pytest` runs them.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sources.nasa_firms import (
    PILOT_BBOX,
    FirmsClient,
    _mock_detections,
    _parse_acq,
    _parse_csv,
)


def test_mock_detections_are_inside_bbox() -> None:
    bbox = PILOT_BBOX["kebbi"]
    rows = _mock_detections(bbox)
    assert len(rows) == 3
    w, s, e, n = bbox
    for r in rows:
        assert w <= r.longitude <= e
        assert s <= r.latitude <= n


def test_mock_client_returns_data_when_no_map_key(monkeypatch) -> None:
    # Clear the cached settings + env var so we exercise the empty-key path
    # even when .env has a real key configured.
    monkeypatch.setenv("NASA_FIRMS_MAP_KEY", "")
    from config import get_settings
    get_settings.cache_clear()
    client = FirmsClient()
    assert client.configured is False


def test_parse_acq_combines_date_and_time() -> None:
    dt = _parse_acq("2026-05-14", "0630")
    assert dt == datetime(2026, 5, 14, 6, 30, tzinfo=timezone.utc)


def test_parse_acq_handles_short_time_strings() -> None:
    assert _parse_acq("2026-05-14", "5") == datetime(
        2026, 5, 14, 0, 5, tzinfo=timezone.utc
    )
    assert _parse_acq("2026-05-14", None) == datetime(
        2026, 5, 14, 0, 0, tzinfo=timezone.utc
    )


def test_parse_csv_handles_modis_row() -> None:
    csv_text = (
        "country_id,latitude,longitude,bright_ti4,brightness,scan,track,acq_date,"
        "acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"
        "NGA,12.74,4.52,,332.4,0.5,0.5,2026-05-14,0930,Terra,MODIS,85,6.1NRT,295.1,18.4,D\n"
    )
    [row] = list(_parse_csv(csv_text))
    assert row.latitude == pytest.approx(12.74)
    assert row.longitude == pytest.approx(4.52)
    assert row.brightness_k == pytest.approx(332.4)
    assert row.bright_t31_k == pytest.approx(295.1)
    assert row.satellite == "Terra"
    assert row.instrument == "MODIS"
    assert row.confidence == "85"
    assert row.frp == pytest.approx(18.4)
    assert row.daynight == "D"


def test_parse_csv_skips_empty_floats() -> None:
    # 15 columns in the header; the row must have 15 comma-separated fields
    csv_text = (
        "country_id,latitude,longitude,brightness,scan,track,acq_date,acq_time,"
        "satellite,instrument,confidence,version,bright_t31,frp,daynight\n"
        "NGA,12.0,4.0,,,,2026-05-14,0000,Aqua,MODIS,nominal,,,,N\n"
    )
    [row] = list(_parse_csv(csv_text))
    assert row.brightness_k is None
    assert row.frp is None
    assert row.daynight == "N"
    assert row.satellite == "Aqua"
    assert row.confidence == "nominal"
