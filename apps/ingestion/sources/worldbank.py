"""World Bank Indicators API client — national economic anchor (Module 06).

The World Bank Indicators API (v2) is keyless, open (CC BY 4.0), and carries
~16k time series for ~200 economies. We use it as the **national anchor** for
the Economic Mobility Compass: real per-country economic levels that we then
disaggregate to per-LGA estimates using a transparent, documented model.

What is REAL here vs MODELLED:
  * REAL  — the national income level (GNI per capita, current local currency,
            `NY.GNP.PCAP.CN`) and its observation year, fetched live.
  * MODEL — the per-LGA spread of cost-of-living + income. No public source
            (NBS included) publishes true per-LGA cost-of-living, so the
            within-country spatial pattern is a deterministic model anchored
            to the curated per-tenant profile. Rows are tagged
            source='worldbank_v1' so the dashboard shows the provenance.

Phase 1 covers the Nigerian pilots only: `NY.GNP.PCAP.CN` returns Naira for
NGA, so no FX conversion is needed to populate `avg_household_income_ngn`.
Ghana/Senegal (LCU = Cedi / CFA) need an FX step and land in a later phase.

No API key. Network failure raises WorldBankError — we never silently
substitute synthetic data for a row labelled as live.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx

from config import get_settings
from sources.nbs_stats import TENANT_COL_PROFILE, MobilityIndicator

log = logging.getLogger(__name__)


SOURCE_WORLDBANK = "worldbank_v1"

# GNI per capita, current local currency (Naira for NGA — no FX needed).
INDICATOR_GNI_PC_LCU = "NY.GNP.PCAP.CN"
# Consumer price index (2010 = 100) — inflation context, optional.
INDICATOR_CPI = "FP.CPI.TOTL"

# Tenant → ISO3. Phase 1 income anchor is Nigeria-only (LCU = NGN); the
# ECOWAS pilots are mapped for completeness but skipped until FX lands.
TENANT_TO_ISO3: dict[str, str] = {
    "kebbi": "NGA", "benue": "NGA", "plateau": "NGA", "kaduna": "NGA",
    "niger": "NGA", "zamfara": "NGA", "nasarawa": "NGA", "fct": "NGA",
    "ghana": "GHA", "senegal": "SEN",
}

# Transparent income model (Phase-1 assumptions, tunable):
#   household monthly income = GNI/capita(LCU) × size × disposable-share ÷ 12
AVG_HOUSEHOLD_SIZE = 4.6          # Nigeria avg household size (NBS NLSS)
DISPOSABLE_INCOME_RATIO = 0.42    # share of per-capita GNI reaching households


@dataclass(frozen=True, slots=True)
class WorldBankObservation:
    indicator: str
    value: float
    year: int


@dataclass(frozen=True, slots=True)
class CountryAnchor:
    """National economic anchor for one country."""

    iso3: str
    gni_per_capita_lcu: float | None
    gni_year: int | None
    cpi: float | None
    cpi_year: int | None


class WorldBankError(RuntimeError):
    """Non-200 or malformed body from the World Bank API."""


def _hash_unit(*parts: str) -> float:
    """Deterministic [0, 1) draw — same construction as the seed/mock paths."""
    h = hashlib.md5("|".join(parts).encode(), usedforsecurity=False).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


class WorldBankClient:
    """Async client for the keyless World Bank Indicators API (v2)."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        """Keyless API — always configured."""
        return True

    async def fetch_observation(
        self, iso3: str, indicator: str,
    ) -> WorldBankObservation | None:
        """Most-recent non-empty value for one country × indicator.

        Returns None when the API has no value for that series; raises
        WorldBankError on transport/format failure.
        """
        url = f"{self._settings.worldbank_api_base_url}/country/{iso3}/indicator/{indicator}"
        async with self._http_ctx() as client:
            resp = await client.get(
                url,
                params={"format": "json", "mrnev": "1"},
                headers={"Accept": "application/json"},
                timeout=30.0,
                follow_redirects=True,
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise WorldBankError(
                f"World Bank {indicator} {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise WorldBankError(
                f"World Bank {indicator}: non-JSON body: {resp.text[:200]}"
            ) from exc
        return _parse_observation(payload, indicator)

    async def fetch_country_anchor(self, iso3: str) -> CountryAnchor:
        """Fetch the small national indicator set for one country.

        GNI is the required income anchor — its failure propagates so the
        caller writes nothing rather than a fake row. CPI is optional
        context; the World Bank API occasionally returns a transient 400/XML
        error, and a flaky CPI fetch must not discard a good GNI.
        """
        gni = await self.fetch_observation(iso3, INDICATOR_GNI_PC_LCU)
        try:
            cpi = await self.fetch_observation(iso3, INDICATOR_CPI)
        except WorldBankError as exc:
            log.warning("World Bank CPI fetch degraded for %s: %s", iso3, exc)
            cpi = None
        return CountryAnchor(
            iso3=iso3,
            gni_per_capita_lcu=gni.value if gni else None,
            gni_year=gni.year if gni else None,
            cpi=cpi.value if cpi else None,
            cpi_year=cpi.year if cpi else None,
        )

    def _http_ctx(self) -> "httpx.AsyncClient | _Borrowed":
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


def _parse_observation(
    payload: object, indicator: str,
) -> WorldBankObservation | None:
    """Translate the World Bank `[meta, [rows]]` envelope to an observation."""
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    rows = payload[1]
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("value") is None:
            continue
        try:
            return WorldBankObservation(
                indicator=indicator,
                value=float(row["value"]),
                year=int(row["date"]),
            )
        except (TypeError, ValueError, KeyError):
            continue
    return None


def compose_mobility_indicators(
    tenant_id: str,
    lgas: list[str],
    anchor: CountryAnchor,
) -> list[MobilityIndicator]:
    """Disaggregate a national income anchor into per-LGA estimates.

    The income LEVEL is real (World Bank GNI per capita); the within-country
    spatial spread is modelled around the curated per-tenant profile. Raises
    ValueError if the anchor carries no usable income figure.
    """
    if anchor.gni_per_capita_lcu is None:
        raise ValueError(f"no GNI per capita for {anchor.iso3}")

    col_anchor, col_spread = TENANT_COL_PROFILE.get(tenant_id, (100.0, 12.0))
    national_monthly_household = (
        anchor.gni_per_capita_lcu * AVG_HOUSEHOLD_SIZE * DISPOSABLE_INCOME_RATIO / 12
    )

    out: list[MobilityIndicator] = []
    for lga in lgas:
        col_unit = _hash_unit(tenant_id, lga, "wb_col")
        col_index = max(0.0, min(300.0, col_anchor + (col_unit - 0.5) * col_spread * 2))
        # Income tracks the LGA's relative cost (pricier LGAs earn more) with
        # small deterministic noise, scaled by the real national level.
        income_noise = 0.9 + _hash_unit(tenant_id, lga, "wb_income") * 0.2
        income = int(national_monthly_household * (col_index / col_anchor) * income_noise)
        opp_unit = _hash_unit(tenant_id, lga, "wb_opportunity")
        opportunity = max(0.05, min(0.95,
            0.20 + (col_index - 70) / 100 * 0.50 + (opp_unit - 0.5) * 0.20))
        cap_unit = _hash_unit(tenant_id, lga, "wb_capacity")
        capacity = max(0.10, min(0.92,
            0.30 + (col_index - 70) / 200 + (cap_unit - 0.5) * 0.30))
        pop_unit = _hash_unit(tenant_id, lga, "wb_pop")
        population = int(40_000 + pop_unit * 280_000)

        out.append(MobilityIndicator(
            lga=lga,
            cost_of_living_index=round(col_index, 1),
            avg_household_income_ngn=income,
            income_opportunity_score=round(opportunity, 3),
            displacement_capacity_index=round(capacity, 3),
            population=population,
            source=SOURCE_WORLDBANK,
        ))
    return out


class _Borrowed:
    """Async-context wrapper that does NOT close an injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
