"""ShockGuard forecast side (ECMWF open data): HTTP contract, response shape, and
the rules around it. DB-free — CI has no Postgres, so the endpoint bodies are
called directly with the repository faked.
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
from routers import shockguard_forecast as sf

client = TestClient(app)


def _request(tenant: str = "kebbi") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant_id=tenant, trace_id=uuid4()))


def _row(lga: str, *, aifs: bool = True) -> dict:
    return {
        "lga": lga, "run_at": datetime(2026, 11, 17, tzinfo=timezone.utc),
        "first_day": date(2026, 11, 17), "cells": 9,
        "rain_ifs_mm": [0.0] * 15, "rain_ifs_max_mm": [0.1] * 15,
        "rain_aifs_mm": [0.0] * 15 if aifs else None,
        "chance_1mm": [0] * 10, "chance_10mm": [0] * 10, "chance_25mm": [0] * 10,
        "chance_50mm": [0] * 10, "temp_dawn_c": [21.0] * 6, "temp_afternoon_c": [36.0] * 6,
    }


# ─── HTTP contract ────────────────────────────────────────────────────────


def test_forecast_without_tenant_header_returns_400() -> None:
    assert client.get("/api/v1/shockguard/forecast").status_code == 400


def test_forecast_cells_without_tenant_header_returns_400() -> None:
    assert client.get("/api/v1/shockguard/forecast/cells").status_code == 400


def test_both_endpoints_are_published() -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/v1/shockguard/forecast" in paths
    assert "/api/v1/shockguard/forecast/cells" in paths


def test_forecast_sits_behind_the_shockguard_module_gate() -> None:
    """Same prefix as the observed side, so the same entitlement applies."""
    from middleware.module_access import _module_for_path

    assert _module_for_path("/api/v1/shockguard/forecast") == "shockguard"
    assert _module_for_path("/api/v1/shockguard/forecast/cells") == "shockguard"


# ─── response shape ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forecast_returns_fifteen_days_and_real_places(monkeypatch) -> None:
    async def _rows(session):  # noqa: ANN001, ANN202
        return [_row("Augie"), _row("Not An LGA", aifs=False)]

    async def _feed(session, tenant):  # noqa: ANN001, ANN202
        return {"last_success_at": datetime(2026, 11, 17, 9, 16, tzinfo=timezone.utc),
                "last_run_at": None, "last_status": "succeeded", "last_error": None}

    monkeypatch.setattr(repo, "latest_forecast", _rows)
    monkeypatch.setattr(repo, "feed_status", _feed)
    out = (await sf.get_forecast(_request(), session=None)).data
    assert len(out.days) == 15 and out.days[0] == date(2026, 11, 17) and out.days[-1] == date(2026, 12, 1)
    augie, unknown = out.areas
    assert augie.location is not None, "a real LGA gets its centroid for the map halo"
    assert unknown.location is None
    assert unknown.rain_aifs_mm is None, "a missing AI-model run stays missing"
    assert "CC BY 4.0" in out.attribution and "does not endorse" in out.attribution


@pytest.mark.asyncio
async def test_before_the_first_run_the_answer_is_empty_not_an_error(monkeypatch) -> None:
    async def _none(session):  # noqa: ANN001, ANN202
        return []

    async def _feed(session, tenant):  # noqa: ANN001, ANN202
        return {"last_success_at": None, "last_run_at": None, "last_status": None, "last_error": None}

    monkeypatch.setattr(repo, "latest_forecast", _none)
    monkeypatch.setattr(repo, "feed_status", _feed)
    out = (await sf.get_forecast(_request(), session=None)).data
    assert out.areas == [] and out.days == [] and out.run_at is None


def test_jsonb_may_arrive_as_text_or_list() -> None:
    assert repo.as_list("[1.5, 2]") == [1.5, 2]
    assert repo.as_list([3]) == [3]
    assert repo.as_list(None) is None


# ─── rules around the feed ────────────────────────────────────────────────


def test_the_watchdog_watches_the_forecast_feed() -> None:
    """A source that runs but has no budget is flagged as unmonitored every morning."""
    from services.feed_health import FEED_MAX_AGE_HOURS

    assert FEED_MAX_AGE_HOURS.get(repo.FORECAST_SOURCE) == 72


def test_the_forecast_is_not_an_observed_side_feed_row() -> None:
    """LIVE_SCAN_SOURCES counts shock_events per feed; a forecast raises none, and a
    row reading "no signal" for it would be wrong. Its status travels in its own
    response instead."""
    from routers.shockguard import LIVE_SCAN_SOURCES

    assert repo.FORECAST_SOURCE not in LIVE_SCAN_SOURCES


def test_migration_covers_every_pilot_and_keeps_every_run() -> None:
    mig = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
    src = (mig / "0062_create_ecmwf_forecast.py").read_text(encoding="utf-8")
    tenants = re.search(r"PILOT_TENANTS.*?\)", src, re.S).group(0)
    for tenant in ("kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
                   "fct", "ghana", "senegal", "nasarawa"):
        assert f'"{tenant}"' in tenants
    assert "UNIQUE (lga, run_at)" in src and "UNIQUE (run_at)" in src
    upgrade = src.split("def downgrade")[0].upper()
    assert "DELETE FROM" not in upgrade and "TRUNCATE " not in upgrade
