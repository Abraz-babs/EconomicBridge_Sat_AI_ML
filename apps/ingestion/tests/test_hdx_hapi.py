"""Tests for the HDX HAPI client + Module 02 aid-coordination ingest.

HTTP is stubbed with httpx.MockTransport (HAPI is keyless). The DB is a
recording fake. What we pin:

  * slugify + app-identifier derivation (base64 "app:email", no token stored).
  * operational-presence parsing, admin1 client-side filter, pagination,
    non-200 -> HapiError.
  * _aggregate: sectors collapse to one coverage row, latest period wins.
  * ingest: registers agencies + writes hapi_v1 coverage rows; unmapped
    tenant and empty-presence both no-op cleanly.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

import sources.hdx_hapi as hapi_mod
from sources.hdx_hapi import HapiClient, HapiError, OrgPresence, slugify
from tasks.aid_ingest import SOURCE_HAPI, _aggregate, ingest_aid_for_tenant


# ─── slugify + app identifier ──────────────────────────────────────────────


def test_slugify_kebab_and_cap():
    assert slugify("Action Against Hunger") == "action-against-hunger"
    assert slugify("Norwegian Refugee Council (NRC)") == "norwegian-refugee-council-nrc"
    assert len(slugify("x" * 80)) <= 40
    assert slugify("   ") == "unknown"


def test_app_identifier_is_base64_app_email():
    client = HapiClient()
    decoded = base64.b64decode(client._app_identifier()).decode()
    assert ":" in decoded  # "<app>:<email>"


# ─── HAPI client ───────────────────────────────────────────────────────────


def _row(admin1: str, admin2: str, org: str, acr: str, sector: str = "Food Security",
         end: str = "2024-12-31") -> dict[str, Any]:
    return {
        "admin1_name": admin1, "admin2_name": admin2, "admin2_code": "NG008001",
        "org_name": org, "org_acronym": acr, "sector_name": sector,
        "reference_period_end": end,
    }


def _client(handler) -> HapiClient:
    return HapiClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_fetch_filters_by_admin1():
    rows = [
        _row("Benue", "Makurdi", "Action Against Hunger", "AAH"),
        _row("Adamawa", "Demsa", "Other Org", "OTH"),
    ]
    def handler(req):
        return httpx.Response(200, content=json.dumps({"data": rows}).encode())
    out = await _client(handler).fetch_operational_presence(
        location_code="NGA", admin1_name="Benue",
    )
    assert len(out) == 1
    assert out[0].admin2_name == "Makurdi"
    assert out[0].org_acronym == "AAH"


@pytest.mark.asyncio
async def test_fetch_paginates(monkeypatch):
    monkeypatch.setattr(hapi_mod, "_PAGE_SIZE", 2)

    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params.get("offset", "0"))
        if offset == 0:
            data = [_row("Benue", "Makurdi", "A", "A"), _row("Benue", "Gboko", "B", "B")]
        else:
            data = [_row("Benue", "Vandeikya", "C", "C")]
        return httpx.Response(200, content=json.dumps({"data": data}).encode())

    out = await _client(handler).fetch_operational_presence(location_code="NGA")
    assert len(out) == 3


@pytest.mark.asyncio
async def test_fetch_non_200_raises():
    def handler(req):
        return httpx.Response(503, content=b"unavailable")
    with pytest.raises(HapiError):
        await _client(handler).fetch_operational_presence(location_code="NGA")


# ─── _aggregate ────────────────────────────────────────────────────────────


def test_aggregate_collapses_sectors_and_keeps_latest():
    presences = [
        OrgPresence("Benue", "Makurdi", "NG008001", "Action Against Hunger", "AAH",
                    "Food Security", "2024-06-30"),
        OrgPresence("Benue", "Makurdi", "NG008001", "Action Against Hunger", "AAH",
                    "WASH", "2024-12-31"),
        OrgPresence("Benue", "Gboko", "NG008002", "Norwegian Refugee Council", "NRC",
                    "Protection", "2024-06-30"),
    ]
    agencies, coverage = _aggregate(presences)
    # Slug prefers the acronym when present (AAH, NRC).
    assert set(agencies) == {"aah", "nrc"}
    # One org across two sectors in one LGA collapses to a single coverage row,
    # taking the most recent reference period.
    assert coverage[("aah", "Makurdi")].isoformat() == "2024-12-31"
    assert ("nrc", "Gboko") in coverage


# ─── ingest (recording fake session) ───────────────────────────────────────


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        self.statements.append((" ".join(str(stmt).split()), dict(params or {})))

        class _R:
            def mappings(self):
                return self

            def all(self):
                return []

        return _R()

    async def commit(self) -> None:
        pass


@pytest.mark.asyncio
async def test_ingest_writes_agencies_and_hapi_coverage():
    rows = [
        _row("Benue", "Makurdi", "Action Against Hunger", "AAH", "Food Security"),
        _row("Benue", "Makurdi", "Action Against Hunger", "AAH", "WASH"),
        _row("Benue", "Gboko", "Norwegian Refugee Council", "NRC", "Protection"),
        _row("Adamawa", "Demsa", "Filtered Out", "FO"),  # wrong state — dropped
    ]
    def handler(req):
        return httpx.Response(200, content=json.dumps({"data": rows}).encode())
    session = _FakeSession()
    result = await ingest_aid_for_tenant(
        session, tenant_id="benue", client=_client(handler),
    )
    assert result.coverage_rows == 2
    assert result.lgas_covered == 2
    agency_ins = [p for s, p in session.statements
                  if s.startswith("INSERT INTO public.aid_agencies")]
    cov_ins = [p for s, p in session.statements
               if s.startswith("INSERT INTO aid_coverage")]
    assert len(agency_ins) == 2
    assert len(cov_ins) == 2
    assert all(p["source"] == SOURCE_HAPI for p in cov_ins)


@pytest.mark.asyncio
async def test_ingest_unmapped_tenant_noops():
    session = _FakeSession()
    result = await ingest_aid_for_tenant(session, tenant_id="atlantis")
    assert result.coverage_rows == 0
    assert session.statements == []
