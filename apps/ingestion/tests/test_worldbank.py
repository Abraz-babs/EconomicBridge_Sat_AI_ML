"""Tests for the World Bank Indicators client + Module 06 anchor ingest.

HTTP is stubbed with httpx.MockTransport (keyless API, so no creds). The DB
is stubbed with a fake session. What we pin:

  * Envelope parsing: `[meta, [rows]]` → observation; error/null → None.
  * fetch_observation: 404 → None, non-200 → WorldBankError.
  * fetch_country_anchor: combines GNI + CPI.
  * compose_mobility_indicators: per-LGA rows tagged worldbank_v1, income
    scales with the national anchor, deterministic, raises without GNI.
  * ingest: writes worldbank_v1 rows for Nigerian tenants; skips others.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sources.worldbank import (
    INDICATOR_CPI,
    INDICATOR_EMP_POP_RATIO,
    INDICATOR_GNI_PC_LCU,
    SOURCE_WORLDBANK,
    CountryAnchor,
    WorldBankClient,
    WorldBankError,
    _parse_observation,
    compose_mobility_indicators,
)
from tasks.mobility_ingest import ingest_mobility_worldbank_for_tenant


# ─── HTTP stubs ────────────────────────────────────────────────────────────


def _wb_transport(
    *, gni: float = 1_500_000.0, gni_year: str = "2023",
    cpi: float = 520.0, cpi_year: str = "2023",
    emp: float = 80.0, emp_year: str = "2025",
) -> httpx.MockTransport:
    """Mock the World Bank API, branching on the indicator in the URL path."""
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if INDICATOR_GNI_PC_LCU in path:
            body: Any = [{"page": 1, "total": 1}, [
                {"indicator": {"id": INDICATOR_GNI_PC_LCU},
                 "countryiso3code": "NGA", "date": gni_year, "value": gni}]]
        elif INDICATOR_CPI in path:
            body = [{"page": 1}, [
                {"indicator": {"id": INDICATOR_CPI},
                 "date": cpi_year, "value": cpi}]]
        elif INDICATOR_EMP_POP_RATIO in path:
            body = [{"page": 1}, [
                {"indicator": {"id": INDICATOR_EMP_POP_RATIO},
                 "date": emp_year, "value": emp}]]
        else:
            body = [{"message": [{"id": "120", "value": "not found"}]}]
        return httpx.Response(200, content=json.dumps(body).encode())
    return httpx.MockTransport(handler)


def _wb_client(**kw: Any) -> WorldBankClient:
    return WorldBankClient(http=httpx.AsyncClient(transport=_wb_transport(**kw)))


# ─── Envelope parsing ──────────────────────────────────────────────────────


def test_parse_observation_reads_value_and_year():
    payload = [{"page": 1}, [{"date": "2023", "value": 1234.5}]]
    obs = _parse_observation(payload, "X")
    assert obs is not None
    assert obs.value == 1234.5
    assert obs.year == 2023


def test_parse_observation_handles_error_envelope():
    assert _parse_observation([{"message": [{"id": "120"}]}], "X") is None


def test_parse_observation_skips_null_values():
    payload = [{"page": 1}, [{"date": "2023", "value": None}]]
    assert _parse_observation(payload, "X") is None


# ─── Client ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_observation_parses_latest_value():
    obs = await _wb_client(gni=1_500_000.0, gni_year="2023").fetch_observation(
        "NGA", INDICATOR_GNI_PC_LCU,
    )
    assert obs is not None
    assert obs.value == 1_500_000.0
    assert obs.year == 2023


@pytest.mark.asyncio
async def test_fetch_country_anchor_combines_indicators():
    anchor = await _wb_client(
        gni=1_500_000.0, cpi=520.0, emp=80.0,
    ).fetch_country_anchor("NGA")
    assert anchor.gni_per_capita_lcu == 1_500_000.0
    assert anchor.cpi == 520.0
    assert anchor.gni_year == 2023
    # WB returns employment as a percentage; anchor stores a 0..1 fraction.
    assert anchor.employment_ratio == pytest.approx(0.80)
    assert anchor.employment_year == 2025


@pytest.mark.asyncio
async def test_country_anchor_survives_flaky_cpi():
    """A transient CPI error must not discard a good GNI (regression: the
    World Bank API returned a 400/XML page on CPI for one tenant)."""
    def handler(req: httpx.Request) -> httpx.Response:
        if INDICATOR_GNI_PC_LCU in req.url.path:
            body = [{"page": 1}, [{"date": "2023", "value": 1_500_000.0}]]
            return httpx.Response(200, content=json.dumps(body).encode())
        return httpx.Response(400, content=b"<?xml?> bad request")
    client = WorldBankClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    anchor = await client.fetch_country_anchor("NGA")
    assert anchor.gni_per_capita_lcu == 1_500_000.0
    # Both optional indicators (CPI + employment) flaked → None, GNI survives.
    assert anchor.cpi is None
    assert anchor.employment_ratio is None


@pytest.mark.asyncio
async def test_fetch_observation_404_returns_none():
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    client = WorldBankClient(http=httpx.AsyncClient(transport=transport))
    assert await client.fetch_observation("NGA", "X") is None


@pytest.mark.asyncio
async def test_fetch_observation_non_200_raises():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, content=b"oops"))
    client = WorldBankClient(http=httpx.AsyncClient(transport=transport))
    with pytest.raises(WorldBankError):
        await client.fetch_observation("NGA", "X")


# ─── compose_mobility_indicators ───────────────────────────────────────────


def test_compose_tags_worldbank_source():
    anchor = CountryAnchor("NGA", 1_500_000.0, 2023, 520.0, 2023)
    rows = compose_mobility_indicators("kebbi", ["Argungu", "Jega"], anchor)
    assert len(rows) == 2
    assert all(r.source == SOURCE_WORLDBANK for r in rows)
    assert all(r.avg_household_income_ngn > 0 for r in rows)


def test_compose_income_scales_with_national_anchor():
    low = CountryAnchor("NGA", 1_000_000.0, 2023, None, None)
    high = CountryAnchor("NGA", 3_000_000.0, 2023, None, None)
    lgas = ["Argungu", "Jega"]
    lo_rows = compose_mobility_indicators("kebbi", lgas, low)
    hi_rows = compose_mobility_indicators("kebbi", lgas, high)
    for lo, hi in zip(lo_rows, hi_rows):
        assert hi.avg_household_income_ngn > lo.avg_household_income_ngn


def test_compose_anchors_opportunity_to_employment():
    """The income-opportunity score tracks the national employment ratio."""
    hi_emp = CountryAnchor("NGA", 1_500_000.0, 2023, None, None,
                           employment_ratio=0.80, employment_year=2025)
    lo_emp = CountryAnchor("NGA", 1_500_000.0, 2023, None, None,
                           employment_ratio=0.40, employment_year=2025)
    hi = compose_mobility_indicators("kebbi", ["Argungu", "Jega"], hi_emp)
    lo = compose_mobility_indicators("kebbi", ["Argungu", "Jega"], lo_emp)
    for h, l in zip(hi, lo):
        assert h.income_opportunity_score > l.income_opportunity_score
    assert all(0.6 <= r.income_opportunity_score <= 0.98 for r in hi)


def test_compose_is_deterministic():
    anchor = CountryAnchor("NGA", 1_500_000.0, 2023, None, None)
    a = compose_mobility_indicators("kebbi", ["Argungu"], anchor)
    b = compose_mobility_indicators("kebbi", ["Argungu"], anchor)
    assert a == b


def test_compose_raises_without_gni():
    with pytest.raises(ValueError, match="no GNI"):
        compose_mobility_indicators(
            "kebbi", ["Argungu"], CountryAnchor("NGA", None, None, None, None),
        )


# ─── Ingest (fake DB session) ──────────────────────────────────────────────


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    """Stub session: returns seed LGA rows for the SELECT, records writes."""

    def __init__(self, seed_rows: list[dict[str, Any]]) -> None:
        self._seed = seed_rows
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        sql = " ".join(str(stmt).split())
        self.statements.append((sql, dict(params or {})))
        if sql.startswith("SELECT lga"):
            return _Result(self._seed)
        return _Result([])

    async def commit(self) -> None:
        pass


_KEBBI_SEED = [
    {"lga": "Argungu", "lon": 4.52, "lat": 12.74},
    {"lga": "Birnin Kebbi", "lon": 4.20, "lat": 12.45},
]


@pytest.mark.asyncio
async def test_ingest_writes_worldbank_rows_for_nigerian_tenant():
    session = _FakeSession(_KEBBI_SEED)
    result = await ingest_mobility_worldbank_for_tenant(
        session, tenant_id="kebbi", client=_wb_client(),
    )
    assert result.source == SOURCE_WORLDBANK
    assert result.rows_upserted == 2
    inserts = [p for s, p in session.statements
               if s.startswith("INSERT INTO mobility_indicators")]
    assert len(inserts) == 2
    assert all(p["source"] == SOURCE_WORLDBANK for p in inserts)
    assert all(p["income"] > 0 for p in inserts)
    # observed_at carries the real World Bank data vintage, not "today".
    assert all(p["observed_at"].year == 2023 for p in inserts)


@pytest.mark.asyncio
async def test_ingest_skips_non_nigerian_tenant():
    session = _FakeSession([])
    result = await ingest_mobility_worldbank_for_tenant(
        session, tenant_id="ghana", client=_wb_client(),
    )
    assert result.rows_upserted == 0
    assert not any(s.startswith("INSERT") for s, _ in session.statements)
