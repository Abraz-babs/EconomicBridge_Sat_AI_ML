"""NBS / ECOWAS STAT cost-of-living client (Module 06 — Mobility).

NBS = Nigeria National Bureau of Statistics. Publishes the Consumer
Price Index (Selected Food + All-Items) and the Nigeria Living
Standards Survey at the state level. ECOWAS STAT is the regional
equivalent for the non-Nigerian pilots (Ghana, Senegal).

This client is the **indicators** layer for the Economic Mobility
Compass: given a tenant + its LGA list, it returns per-LGA
`MobilityIndicator` records (cost-of-living index, avg household
income, opportunity + displacement-capacity composites) that the
mobility_ingest task writes to `mobility_indicators` tagged
source='nbs_col_v1' (or 'ecowas_stat_v1').

Mock fallback: with no API key configured the client returns
deterministic synthetic indicators — same MD5-hash approach as
scripts/seed_mobility_indicators.py but with a distinct salt so the
values differ from the seed_v1 rows. This makes the seed→live swap-in
visible (the dashboard shows source='nbs_col_v1') and lets the whole
pipeline run in dev without credentials. NEVER hardcode the API key.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from config import get_settings

log = logging.getLogger(__name__)


# Per-tenant cost-of-living anchor + LGA spread, mirroring the seed
# profile (scripts/seed_mobility_indicators.py TENANT_COL_PROFILE) so
# mock "live" data sits in the same plausible range as seed_v1 but isn't
# identical to it (different hash salt below).
TENANT_COL_PROFILE: dict[str, tuple[float, float]] = {
    "kebbi":    (78.0, 10.0),
    "benue":    (105.0, 12.0),
    "plateau":  (102.0, 11.0),
    "kaduna":   (94.0, 14.0),
    "niger":    (85.0, 11.0),
    "zamfara":  (76.0, 9.0),
    "nasarawa": (100.0, 13.0),
    "fct":      (150.0, 22.0),
    "ghana":    (108.0, 15.0),
    "senegal":  (114.0, 16.0),
}

# Which statistics body owns each tenant — picks the source tag.
NIGERIAN_TENANTS = frozenset({
    "kebbi", "benue", "plateau", "kaduna", "niger",
    "zamfara", "nasarawa", "fct",
})

SOURCE_NBS = "nbs_col_v1"
SOURCE_ECOWAS = "ecowas_stat_v1"


@dataclass(frozen=True, slots=True)
class MobilityIndicator:
    """One LGA's cost-of-living + income profile from a stats body."""

    lga: str
    cost_of_living_index: float
    avg_household_income_ngn: int
    income_opportunity_score: float
    displacement_capacity_index: float
    population: int
    source: str


class NbsStatsError(RuntimeError):
    """Non-200 response or malformed body from a stats API."""


def source_for_tenant(tenant_id: str) -> str:
    """nbs_col_v1 for Nigerian pilots, ecowas_stat_v1 for the rest."""
    return SOURCE_NBS if tenant_id in NIGERIAN_TENANTS else SOURCE_ECOWAS


def _hash_unit(tenant_id: str, lga: str, salt: str) -> float:
    """Deterministic [0, 1) draw. Same construction as the seed script
    but callers pass a 'live'-prefixed salt so values differ from seed."""
    h = hashlib.md5(
        f"{tenant_id}|{lga}|{salt}".encode(), usedforsecurity=False,
    ).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


class NbsStatsClient:
    """Cost-of-living indicators client with mock fallback.

    The real implementation (when an API key lands) will hit NBS's CPI
    endpoints + the Living Standards Survey, then downscale state-level
    figures to per-LGA via the population-weighted method documented in
    docs (TODO when the API contract is confirmed). For now `configured`
    is False whenever the relevant key is empty and we return mock data.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def configured_for(self, tenant_id: str) -> bool:
        s = self._settings
        if tenant_id in NIGERIAN_TENANTS:
            return bool(s.nbs_api_key)
        return bool(s.ecowas_stat_api_key)

    async def fetch_indicators(
        self, tenant_id: str, lgas: list[str],
    ) -> list[MobilityIndicator]:
        """Return one MobilityIndicator per LGA.

        Real path (key configured) is not built yet — raises
        NotImplementedError so a misconfiguration surfaces loudly rather
        than silently shipping mock data labelled as real. Mock path
        (no key) returns deterministic synthetic indicators.
        """
        if self.configured_for(tenant_id):
            # Guard rail until the real NBS/ECOWAS HTTP integration lands.
            raise NotImplementedError(
                "NBS/ECOWAS live fetch not implemented yet — unset the "
                "API key to use mock mode, or implement the HTTP call."
            )
        log.info(
            "nbs: no API key for tenant=%s — returning mock indicators "
            "(%d LGAs)", tenant_id, len(lgas),
        )
        return self._mock_indicators(tenant_id, lgas)

    def _mock_indicators(
        self, tenant_id: str, lgas: list[str],
    ) -> list[MobilityIndicator]:
        anchor, spread = TENANT_COL_PROFILE.get(tenant_id, (100.0, 12.0))
        src = source_for_tenant(tenant_id)
        out: list[MobilityIndicator] = []
        for lga in lgas:
            # 'live_col' salt → distinct from the seed script's 'col'.
            col_unit = _hash_unit(tenant_id, lga, "live_col")
            col_index = max(0.0, min(300.0,
                anchor + (col_unit - 0.5) * spread * 2,
            ))
            income_unit = _hash_unit(tenant_id, lga, "live_income")
            avg_income = int(
                45_000 + (col_index / 100.0) * 95_000 + income_unit * 35_000
            )
            opp_unit = _hash_unit(tenant_id, lga, "live_opportunity")
            opportunity = max(0.05, min(0.95,
                0.20 + (col_index - 70) / 100 * 0.50 + (opp_unit - 0.5) * 0.20,
            ))
            cap_unit = _hash_unit(tenant_id, lga, "live_capacity")
            capacity = max(0.10, min(0.92,
                0.30 + (col_index - 70) / 200 + (cap_unit - 0.5) * 0.30,
            ))
            pop_unit = _hash_unit(tenant_id, lga, "live_pop")
            population = int(40_000 + pop_unit * 280_000)

            out.append(MobilityIndicator(
                lga=lga,
                cost_of_living_index=round(col_index, 1),
                avg_household_income_ngn=avg_income,
                income_opportunity_score=round(opportunity, 3),
                displacement_capacity_index=round(capacity, 3),
                population=population,
                source=src,
            ))
        return out
