"""UNICEF GIGA + ITU connectivity client (Module 07 — SkillsBridge).

GIGA = UNICEF/ITU initiative mapping every school's internet
connectivity. ITU DataHub provides national/sub-national telecom
coverage statistics. Together they populate the SkillsBridge module's
per-LGA education-access profile: school count + density, internet +
mobile coverage, electricity reliability, and the derived
learning-gap index.

A single source tag `giga_v1` carries the combined row (GIGA supplies
schools, ITU supplies coverage) — both bodies are global so, unlike
the NBS/ECOWAS split in Module 06, there's no per-region routing.

Mock fallback: with no API key the client returns deterministic
synthetic indicators (MD5-hash, 'live_*' salt distinct from the seed
script's). Same swap-in story as Module 06 — proves the seed→live
path without credentials and never silently ships mock data as real.
NEVER hardcode the API keys.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from config import get_settings

log = logging.getLogger(__name__)

SOURCE_GIGA = "giga_v1"

# (internet_pct_anchor, spread, school_density_anchor, electricity_anchor)
# Mirrors scripts/seed_skills_indicators.py TENANT_SKILLS_PROFILE so mock
# "live" data sits in the same plausible band as seed_v1.
TENANT_SKILLS_PROFILE: dict[str, tuple[float, float, float, float]] = {
    "kebbi":    (12.0,  8.0, 1.8, 0.45),
    "benue":    (28.0, 12.0, 2.4, 0.55),
    "plateau":  (26.0, 11.0, 2.6, 0.60),
    "kaduna":   (35.0, 14.0, 3.0, 0.65),
    "niger":    (18.0,  9.0, 2.0, 0.50),
    "zamfara":  (10.0,  7.0, 1.6, 0.40),
    "nasarawa": (30.0, 12.0, 2.5, 0.58),
    "fct":      (65.0, 18.0, 4.2, 0.85),
    "ghana":    (48.0, 16.0, 3.5, 0.72),
    "senegal":  (42.0, 15.0, 3.2, 0.68),
}


@dataclass(frozen=True, slots=True)
class SkillsIndicator:
    """One LGA's education-access profile from GIGA + ITU."""

    lga: str
    school_count: int
    school_density_per_10k: float
    internet_coverage_pct: float
    mobile_coverage_pct: float
    electricity_reliability: float
    youth_population: int
    learning_gap_index: float
    source: str


class GigaItuStatsError(RuntimeError):
    """Non-200 response or malformed body from GIGA / ITU."""


def _hash_unit(tenant_id: str, lga: str, salt: str) -> float:
    """Deterministic [0, 1) draw — same construction as the seed script,
    distinct salt so live values differ from seed_v1."""
    h = hashlib.md5(
        f"{tenant_id}|{lga}|{salt}".encode(), usedforsecurity=False,
    ).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


# Tenant → ISO country code for the GIGA country filter. GIGA maps schools
# per country; we aggregate the returned school points to the tenant's LGAs.
TENANT_TO_GIGA_COUNTRY: dict[str, str] = {
    "kebbi": "NG", "benue": "NG", "plateau": "NG", "kaduna": "NG",
    "niger": "NG", "zamfara": "NG", "nasarawa": "NG", "fct": "NG",
    "ghana": "GH", "senegal": "SN",
}


class GigaItuStatsClient:
    """SkillsBridge indicators client with mock fallback.

    Real path (key configured) hits the GIGA Maps API
    (https://maps.giga.global/docs/explore-api) for school locations +
    connectivity status per country, then aggregates the school points to
    per-LGA `school_count` / `school_density_per_10k` / `internet_coverage`.
    ITU DataHub supplies national coverage context; the learning-gap index
    stays a documented composite (same real-vs-modelled split as Module 06).

    NOT yet wired to the live endpoint: the exact GIGA schools/measurements
    paths + JSON field names need verifying against a real key + sample
    response first (the docs page is JS-rendered and the key is gated behind
    Azure AD B2C sign-up). Until then a configured key raises
    NotImplementedError rather than silently shipping mock data as 'live'.

    To finish (≈30 min once a key + one sample response are in hand):
      1. confirm the schools endpoint path + auth header at /docs/explore-api
      2. implement `_fetch_schools(country)` (httpx + Bearer/api-key header)
      3. map school points → LGA via admin-2 name, fill SkillsIndicator
      4. add a contract test against the real sample payload
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        s = self._settings
        # Either body counts as "configured" — GIGA for schools or ITU
        # for coverage. In practice the operator sets both.
        return bool(s.giga_api_key or s.itu_api_key)

    async def fetch_indicators(
        self, tenant_id: str, lgas: list[str],
    ) -> list[SkillsIndicator]:
        if self.configured:
            raise NotImplementedError(
                "GIGA/ITU live fetch not wired yet. Key auth is confirmed "
                "(register at https://maps.giga.global, request a key via "
                "their API-keys admin); the schools endpoint path + response "
                "field names still need verifying against a live key before "
                "this ships. Unset GIGA_API_KEY/ITU_API_KEY to use mock mode."
            )
        log.info(
            "giga_itu: no API key for tenant=%s — returning mock "
            "indicators (%d LGAs)", tenant_id, len(lgas),
        )
        return self._mock_indicators(tenant_id, lgas)

    def _mock_indicators(
        self, tenant_id: str, lgas: list[str],
    ) -> list[SkillsIndicator]:
        net_anchor, net_spread, density_anchor, power_anchor = (
            TENANT_SKILLS_PROFILE.get(tenant_id, (25.0, 10.0, 2.5, 0.55))
        )
        out: list[SkillsIndicator] = []
        for lga in lgas:
            net_unit = _hash_unit(tenant_id, lga, "live_net")
            internet_pct = max(0.5, min(98.0,
                net_anchor + (net_unit - 0.5) * net_spread * 2,
            ))
            mob_unit = _hash_unit(tenant_id, lga, "live_mob")
            mobile_pct = max(5.0, min(99.0, internet_pct + 18 + mob_unit * 18))

            density_unit = _hash_unit(tenant_id, lga, "live_density")
            density = max(0.3,
                density_anchor + (density_unit - 0.5) * density_anchor * 0.6,
            )
            power_unit = _hash_unit(tenant_id, lga, "live_power")
            electricity = max(0.10, min(0.98,
                power_anchor + (power_unit - 0.5) * 0.25,
            ))
            pop_unit = _hash_unit(tenant_id, lga, "live_pop")
            youth_pop = int(18_000 + pop_unit * 130_000)
            school_count = max(1, int(density * (youth_pop / 10_000)))

            internet_norm = internet_pct / 100.0
            density_norm = min(1.0, density / 5.0)
            gap = max(0.05, min(0.98,
                (1 - internet_norm) * 0.4
                + (1 - density_norm) * 0.3
                + (1 - electricity) * 0.3,
            ))

            out.append(SkillsIndicator(
                lga=lga,
                school_count=school_count,
                school_density_per_10k=round(density, 2),
                internet_coverage_pct=round(internet_pct, 1),
                mobile_coverage_pct=round(mobile_pct, 1),
                electricity_reliability=round(electricity, 3),
                youth_population=youth_pop,
                learning_gap_index=round(gap, 3),
                source=SOURCE_GIGA,
            ))
        return out
