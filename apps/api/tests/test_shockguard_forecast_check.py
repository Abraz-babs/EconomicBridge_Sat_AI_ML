"""Forecast check (ECMWF forecast vs NASA IMERG): HTTP contract, response shape,
and the rules around it. DB-free — the endpoint bodies are called directly with
the repositories faked, as in test_shockguard_forecast.py.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from repositories import forecast as repo
from repositories import forecast_check as check_repo
from routers import shockguard_forecast as sf

client = TestClient(app)


def _request(tenant: str = "ghana") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant_id=tenant, trace_id=uuid4()))


async def _feed(session, tenant, source="x"):  # noqa: ANN001, ANN202
    assert source == check_repo.CHECK_SOURCE, "the check reports its own feed, not the forecast's"
    return {"last_success_at": None, "last_run_at": None, "last_status": "succeeded", "last_error": None}


def _summary() -> dict:
    lead = [5, 2, 1, 22, 40.0, 38.5, 12.0, 8]
    return {
        "version": 1, "wet_mm": 1.0, "thresholds": [1, 10, 25, 50], "leads": 15,
        "shown_leads": [0, 1, 2, 3, 5, 7, 9, 14], "chance_bins": [0, 10, 30, 50, 70, 90, 101],
        "chance_groups": ["0-2", "3-5", "6-9"], "first_day": "2026-05-01", "last_day": "2026-11-16",
        "days_checked": 200, "lga_days": 52000, "pairs": 700000, "recent_days": 30,
        "recent_from": "2026-10-18",
        "scorecard": {"all": {"ifs": [lead] * 15, "aifs": [lead] * 15},
                      "recent": {"ifs": [lead] * 15, "aifs": [lead] * 15}},
        "chances": {"1": {"brier": [[100, 0.1, 0.2]] * 10, "bins": {"0-2": [[10, 50.0, 0.4]] * 6}}},
        "ribbon": [{"day": "2026-11-16", "lgas": 260, "wet": 40, "max_mm": 37.5, "max_lga": "Tarkwa Nsuaem",
                    "ifs": [[30, 5, 10, 215]] * 8, "aifs": [[28, 4, 12, 216]] * 8}],
        "lgas": [{"lga": "Tarkwa Nsuaem", "days": 200, "wet": 90, "ifs": [[60, 10, 30, 100, 900.0, 950.5]] * 8,
                  "aifs": [[55, 8, 35, 102, 850.0, 950.5]] * 8},
                 {"lga": "Not A District", "days": 3, "wet": 0, "ifs": [[0, 0, 0, 3, 0.0, 0.0]] * 8,
                  "aifs": [[0, 0, 0, 3, 0.0, 0.0]] * 8}],
    }


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_check_endpoints_need_a_tenant() -> None:
    assert client.get("/api/v1/shockguard/forecast/check").status_code == 400
    assert client.get("/api/v1/shockguard/forecast/check/day").status_code == 400


def test_check_endpoints_are_published_behind_the_shockguard_gate() -> None:
    from middleware.module_access import _module_for_path

    paths = client.get("/api/openapi.json").json()["paths"]
    for p in ("/api/v1/shockguard/forecast/check", "/api/v1/shockguard/forecast/check/day"):
        assert p in paths
        assert _module_for_path(p) == "shockguard"


# ─── response shape ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_scorecard_travels_with_its_counts_and_places(monkeypatch) -> None:
    async def _latest(session):  # noqa: ANN001, ANN202
        return {"summary": _summary(), "created_at": datetime(2026, 11, 17, 22, 31, tzinfo=timezone.utc)}

    monkeypatch.setattr(check_repo, "latest_summary", _latest)
    monkeypatch.setattr(repo, "feed_status", _feed)
    out = (await sf.get_forecast_check(_request(), session=None)).data
    assert out.days_checked == 200 and out.last_day == date(2026, 11, 16)
    assert out.scorecard["all"]["ifs"][1][:4] == [5, 2, 1, 22], "counts, not just a ratio"
    assert out.ribbon[0].max_lga == "Tarkwa Nsuaem"
    real, unknown = out.lgas
    assert real.location is not None and unknown.location is None
    assert "IMERG" in out.measured_credit and "not a rain gauge" in out.measured_credit
    assert "does not endorse" in out.attribution


@pytest.mark.asyncio
async def test_before_the_first_scorecard_the_answer_is_empty(monkeypatch) -> None:
    async def _none(session):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(check_repo, "latest_summary", _none)
    monkeypatch.setattr(repo, "feed_status", _feed)
    out = (await sf.get_forecast_check(_request(), session=None)).data
    assert out.days_checked == 0 and out.ribbon == [] and out.first_day is None


@pytest.mark.asyncio
async def test_a_day_defaults_to_the_newest_measured(monkeypatch) -> None:
    asked: list[date] = []

    async def _newest(session):  # noqa: ANN001, ANN202
        return date(2026, 11, 16)

    async def _day(session, day):  # noqa: ANN001, ANN202
        asked.append(day)
        return [{"lga": "Tarkwa Nsuaem", "measured_mm": 30.1, "measured_max_mm": 37.5, "wet_share_1mm": 1.0,
                 "wet_share_10mm": 0.9, "ifs_mm": [12.0] + [None] * 14, "aifs_mm": [None] * 15,
                 "chance_1mm": [90.0] + [None] * 9, "chance_10mm": [40.0] + [None] * 9}]

    monkeypatch.setattr(check_repo, "newest_measured_day", _newest)
    monkeypatch.setattr(check_repo, "check_day", _day)
    out = (await sf.get_forecast_check_day(_request(), session=None, day=None)).data
    assert asked == [date(2026, 11, 16)] and out.day == date(2026, 11, 16)
    area = out.areas[0]
    assert area.location is not None and area.ifs_mm[0] == 12.0 and area.aifs_mm[0] is None


# ─── rules around the feed ────────────────────────────────────────────────


def test_the_watchdog_watches_the_check_and_the_overview_names_it() -> None:
    from routers.overview_live import FEED_LABELS
    from services.feed_health import FEED_MAX_AGE_HOURS

    assert FEED_MAX_AGE_HOURS.get(check_repo.CHECK_SOURCE) == 72
    assert check_repo.CHECK_SOURCE in FEED_LABELS


def test_the_check_is_not_an_observed_side_feed_row() -> None:
    """It raises no shock_events; a feed row reading "no signal" for it would be wrong."""
    from routers.shockguard import LIVE_SCAN_SOURCES

    assert check_repo.CHECK_SOURCE not in LIVE_SCAN_SOURCES


def test_the_day_query_reads_only_00_utc_runs_and_the_late_product() -> None:
    import inspect

    src = inspect.getsource(check_repo.check_day)
    assert "EXTRACT(HOUR FROM f.run_at AT TIME ZONE 'UTC') = 0" in src
    assert check_repo.MEASURED_PRODUCT == "GPM_3IMERGDL.07"


def test_migration_covers_every_pilot_and_keeps_every_record() -> None:
    mig = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
    src = (mig / "0063_create_forecast_check.py").read_text(encoding="utf-8")
    tenants = re.search(r"PILOT_TENANTS.*?\)", src, re.S).group(0)
    for tenant in ("kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
                   "fct", "ghana", "senegal", "nasarawa"):
        assert f'"{tenant}"' in tenants
    assert "UNIQUE (lga, day, product)" in src and "UNIQUE (last_day, lga_days, pairs)" in src
    upgrade = src.split("def downgrade")[0].upper()
    assert "DELETE FROM" not in upgrade and "TRUNCATE " not in upgrade
