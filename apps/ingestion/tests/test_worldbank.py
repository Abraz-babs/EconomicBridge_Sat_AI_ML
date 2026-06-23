"""Tests for the World Bank Indicators client + Module 06 anchor ingest.

HTTP is stubbed with httpx.MockTransport (keyless API, so no creds). The DB
is stubbed with a fake session. What we pin:

  * Envelope parsing: `[meta, [rows]]` → observation; error/null → None.
  * fetch_observation: 404 → None, non-200 → WorldBankError.
  * fetch_country_anchor: combines USD + local-currency GNI + CPI + employment;
    optional fetches degrade independently.
  * compose_mobility_indicators: per-LGA rows tagged worldbank_v1; dual currency
    (USD always, NGN for Nigeria only); income scales with the anchor;
    opportunity tracks employment; deterministic; raises without USD GNI.
  * ingest: writes worldbank_v1 rows for every mapped tenant — both currencies
    for Nigeria, USD-only for ECOWAS.
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
    INDICATOR_GNI_PC_USD,
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
    *, usd: float = 1_800.0, usd_year: str = "2024",
    gni: float = 1_500_000.0, gni_year: str = "2023",
    cpi: float = 520.0, cpi_year: str = "2023",
    emp: float = 80.0, emp_year: str = "2025",
) -> httpx.MockTransport:
    """Mock the World Bank API, branching on the indicator in the URL path."""
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if INDICATOR_GNI_PC_USD in path:
            body: Any = [{"page": 1}, [
                {"indicator": {"id": INDICATOR_GNI_PC_USD},
                 "date": usd_year, "value": usd}]]
        elif INDICATOR_GNI_PC_LCU in path:
            body = [{"page": 1, "total": 1}, [
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


def _anchor(**kw: Any) -> CountryAnchor:
    """CountryAnchor with sensible NGA defaults; override per test."""
    base: dict[str, Any] = dict(
        iso3="NGA",
        gni_per_capita_usd=1_800.0, gni_usd_year=2024,
        gni_per_capita_lcu=1_500_000.0, gni_year=2023,
        cpi=None, cpi_year=None,
    )
    base.update(kw)
    return CountryAnchor(**base)


# ─── Envelope parsing ──────────────────────────────────────────────────────


def test_parse_observation_reads_value_and_year():
    payload = [{"page": 1}, [{"date": "2023", "value": 1234.5}]]
    obs = _parse_observation(payload, "X")
    assert obs is not None
    assert obs.value == 1234.5
    assert obs.year == 2023


def test_parse_observation_picks_first_non_null_newest_first():
    # mrv=5 returns newest-first; parser takes the latest non-null.
    payload = [{"page": 1}, [
        {"date": "2025", "value": None},
        {"date": "2024", "value": 2310.0},
        {"date": "2023", "value": 2280.0},
    ]]
    obs = _parse_observation(payload, "X")
    assert obs is not None
    assert obs.year == 2024
    assert obs.value == 2310.0


def test_parse_observation_handles_error_envelope():
    assert _parse_observation([{"message": [{"id": "120"}]}], "X") is None


# ─── Client ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_observation_parses_latest_value():
    obs = await _wb_client(usd=1_800.0, usd_year="2024").fetch_observation(
        "NGA", INDICATOR_GNI_PC_USD,
    )
    assert obs is not None
    assert obs.value == 1_800.0
    assert obs.year == 2024


@pytest.mark.asyncio
async def test_fetch_country_anchor_combines_indicators():
    anchor = await _wb_client().fetch_country_anchor("NGA")
    assert anchor.gni_per_capita_usd == 1_800.0
    assert anchor.gni_usd_year == 2024
    assert anchor.gni_per_capita_lcu == 1_500_000.0
    assert anchor.cpi == 520.0
    # WB returns employment as a percentage; anchor stores a 0..1 fraction.
    assert anchor.employment_ratio == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_country_anchor_survives_flaky_optionals():
    """A transient error on the OPTIONAL indicators (LCU/CPI/employment) must
    not discard a good USD anchor (regression: WB 400s on some pairs)."""
    def handler(req: httpx.Request) -> httpx.Response:
        if INDICATOR_GNI_PC_USD in req.url.path:
            body = [{"page": 1}, [{"date": "2024", "value": 1_800.0}]]
            return httpx.Response(200, content=json.dumps(body).encode())
        return httpx.Response(400, content=b"<?xml?> bad request")
    client = WorldBankClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    anchor = await client.fetch_country_anchor("NGA")
    assert anchor.gni_per_capita_usd == 1_800.0
    assert anchor.gni_per_capita_lcu is None
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


def test_compose_nigeria_has_both_currencies():
    rows = compose_mobility_indicators("kebbi", ["Argungu", "Jega"], _anchor())
    assert len(rows) == 2
    assert all(r.source == SOURCE_WORLDBANK for r in rows)
    assert all(r.avg_household_income_usd and r.avg_household_income_usd > 0 for r in rows)
    assert all(r.avg_household_income_ngn and r.avg_household_income_ngn > 0 for r in rows)


def test_compose_ecowas_is_usd_only():
    """A non-NGA anchor yields USD income only — NGN is None even if a local
    currency figure was fetched (it's Cedi/CFA, not Naira)."""
    ghana = _anchor(iso3="GHA", gni_per_capita_usd=2_310.0, gni_per_capita_lcu=30_000.0)
    rows = compose_mobility_indicators("ghana", ["Bawku", "Tamale"], ghana)
    assert all(r.avg_household_income_usd and r.avg_household_income_usd > 0 for r in rows)
    assert all(r.avg_household_income_ngn is None for r in rows)


def test_compose_income_scales_with_usd_anchor():
    low = _anchor(gni_per_capita_usd=1_000.0)
    high = _anchor(gni_per_capita_usd=3_000.0)
    lgas = ["Argungu", "Jega"]
    lo_rows = compose_mobility_indicators("kebbi", lgas, low)
    hi_rows = compose_mobility_indicators("kebbi", lgas, high)
    for lo, hi in zip(lo_rows, hi_rows):
        assert hi.avg_household_income_usd > lo.avg_household_income_usd


def test_compose_applies_state_prosperity_factor_to_income():
    """Rural-northern income must sit well below the raw national MEAN — the
    old behaviour applied the national mean uniformly and overstated it ~2×."""
    anchor = _anchor()  # LCU 1.5M
    national_mean = 1_500_000 * 4.6 * 0.42 / 12   # pre-factor mean household
    rows = compose_mobility_indicators("kebbi", ["Argungu", "Jega", "Suru"], anchor)
    avg = sum(r.avg_household_income_ngn for r in rows) / len(rows)
    assert avg < national_mean * 0.65   # meaningfully below the national mean
    assert avg > national_mean * 0.30   # but not absurdly low


def test_compose_richer_state_outearns_poorer_state():
    """The prosperity gradient orders states correctly: FCT/Abuja > rural Kebbi."""
    anchor = _anchor()
    kebbi = compose_mobility_indicators("kebbi", ["Argungu", "Jega"], anchor)
    fct = compose_mobility_indicators("fct", ["AMAC", "Kuje"], anchor)
    kebbi_avg = sum(r.avg_household_income_ngn for r in kebbi) / len(kebbi)
    fct_avg = sum(r.avg_household_income_ngn for r in fct) / len(fct)
    assert fct_avg > kebbi_avg


def test_compose_anchors_opportunity_to_employment():
    """The income-opportunity score tracks the national employment ratio."""
    hi = compose_mobility_indicators(
        "kebbi", ["Argungu", "Jega"], _anchor(employment_ratio=0.80))
    lo = compose_mobility_indicators(
        "kebbi", ["Argungu", "Jega"], _anchor(employment_ratio=0.40))
    for h, lo_row in zip(hi, lo):
        assert h.income_opportunity_score > lo_row.income_opportunity_score
    assert all(0.6 <= r.income_opportunity_score <= 0.98 for r in hi)


def test_compose_is_deterministic():
    a = compose_mobility_indicators("kebbi", ["Argungu"], _anchor())
    b = compose_mobility_indicators("kebbi", ["Argungu"], _anchor())
    assert a == b


def test_compose_raises_without_usd_gni():
    with pytest.raises(ValueError, match="no USD GNI"):
        compose_mobility_indicators("kebbi", ["Argungu"], _anchor(gni_per_capita_usd=None))


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


_SEED = [
    {"lga": "Argungu", "lon": 4.52, "lat": 12.74},
    {"lga": "Birnin Kebbi", "lon": 4.20, "lat": 12.45},
]


@pytest.mark.asyncio
async def test_ingest_nigeria_writes_both_currencies():
    session = _FakeSession(_SEED)
    result = await ingest_mobility_worldbank_for_tenant(
        session, tenant_id="kebbi", client=_wb_client(),
    )
    assert result.source == SOURCE_WORLDBANK
    assert result.rows_upserted == 2
    inserts = [p for s, p in session.statements
               if s.startswith("INSERT INTO mobility_indicators")]
    assert len(inserts) == 2
    assert all(p["source"] == SOURCE_WORLDBANK for p in inserts)
    assert all(p["income_usd"] > 0 for p in inserts)
    assert all(p["income_ngn"] > 0 for p in inserts)
    # observed_at carries the real WB USD data vintage, not "today".
    assert all(p["observed_at"].year == 2024 for p in inserts)


@pytest.mark.asyncio
async def test_ingest_ecowas_writes_usd_only():
    session = _FakeSession(_SEED)
    result = await ingest_mobility_worldbank_for_tenant(
        session, tenant_id="ghana", client=_wb_client(),
    )
    assert result.rows_upserted == 2
    inserts = [p for s, p in session.statements
               if s.startswith("INSERT INTO mobility_indicators")]
    assert len(inserts) == 2
    assert all(p["income_usd"] > 0 for p in inserts)
    assert all(p["income_ngn"] is None for p in inserts)


@pytest.mark.asyncio
async def test_ingest_unmapped_tenant_noops():
    session = _FakeSession([])
    result = await ingest_mobility_worldbank_for_tenant(
        session, tenant_id="atlantis", client=_wb_client(),
    )
    assert result.rows_upserted == 0
    assert not any(s.startswith("INSERT") for s, _ in session.statements)
