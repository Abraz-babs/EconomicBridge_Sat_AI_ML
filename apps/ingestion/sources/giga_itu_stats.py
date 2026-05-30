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

import httpx

from config import get_settings

log = logging.getLogger(__name__)

SOURCE_GIGA = "giga_v1"

# Live GIGA Maps API (Node service). The `maps.giga.global` host only serves
# the web app; the api-key data API lives here. Auth: Authorization: Bearer.
GIGA_API_HOST = "https://uni-ooi-giga-maps-service.azurewebsites.net/api/v1"

# Tenant → ISO3 for the GIGA country filter (/schools_location/country/{ISO3}).
TENANT_TO_GIGA_COUNTRY: dict[str, str] = {
    "kebbi": "NGA", "benue": "NGA", "plateau": "NGA", "kaduna": "NGA",
    "niger": "NGA", "zamfara": "NGA", "nasarawa": "NGA", "fct": "NGA",
    "ghana": "GHA", "senegal": "SEN",
}

# A GIGA school is attributed to the nearest pilot-LGA centroid only if within
# this radius (~0.45° ≈ 50 km), so schools far from any pilot LGA aren't
# misattributed. Pilot LGAs are large, so this captures the LGA's schools well.
SCHOOL_BIN_RADIUS_DEG = 0.45

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


def _nearest_lga(
    lon: float, lat: float, lga_coords: dict[str, tuple[float, float]],
) -> str | None:
    """LGA whose centroid is closest to (lon, lat), or None if all are beyond
    SCHOOL_BIN_RADIUS_DEG (so a far-away school isn't misattributed)."""
    best_lga: str | None = None
    best_d2 = SCHOOL_BIN_RADIUS_DEG ** 2
    for lga, (clon, clat) in lga_coords.items():
        d2 = (lon - clon) ** 2 + (lat - clat) ** 2
        if d2 <= best_d2:
            best_d2 = d2
            best_lga = lga
    return best_lga


class GigaItuStatsClient:
    """SkillsBridge indicators client — real GIGA school data + mock fallback.

    Real path (GIGA key configured): pulls every school's location for the
    tenant's country from the GIGA Maps API
    (`/schools_location/country/{ISO3}`, Authorization: Bearer) and bins the
    school points to the tenant's LGAs by nearest centroid → REAL per-LGA
    `school_count` and `school_density_per_10k`.

    What stays MODELLED (this GIGA key is scoped to School Location only;
    connectivity/measurements endpoints 404): `internet_coverage_pct`,
    `mobile_coverage_pct`, `electricity_reliability`, `learning_gap_index`,
    and `youth_population`. Same documented real-vs-modelled split as
    Module 06. To make connectivity real too, request the "School
    Connectivity" API category on the GIGA key.

    Mock path (no key): deterministic synthetic indicators (unchanged).
    """

    # Per-process cache: country ISO3 → list of (lon, lat) school points.
    # The 8 Nigerian tenants share NGA's ~109k schools, so we fetch once.
    _schools_cache: dict[str, list[tuple[float, float]]] = {}

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        # GIGA key drives the real school feed. (ITU is non-commercial and
        # left unset for the commercial pilot.)
        return bool(self._settings.giga_api_key)

    async def fetch_indicators(
        self,
        tenant_id: str,
        lga_coords: dict[str, tuple[float, float]],
        *,
        national_internet_pct: float | None = None,
        national_mobile_pct: float | None = None,
    ) -> list[SkillsIndicator]:
        """Return one SkillsIndicator per LGA.

        `lga_coords` is LGA name → (lon, lat) centroid (from the seed rows),
        needed to bin GIGA school points to LGAs. When `national_internet_pct`
        / `national_mobile_pct` are supplied (real World Bank ICT figures), the
        per-LGA connectivity is anchored to them; otherwise connectivity is
        modelled.
        """
        if not self.configured:
            log.info(
                "giga_itu: no GIGA key for tenant=%s — mock indicators (%d LGAs)",
                tenant_id, len(lga_coords),
            )
            return self._mock_indicators(tenant_id, list(lga_coords))

        iso3 = TENANT_TO_GIGA_COUNTRY.get(tenant_id)
        if not iso3:
            log.warning("giga: no ISO3 for tenant=%s — mock", tenant_id)
            return self._mock_indicators(tenant_id, list(lga_coords))

        schools = await self._fetch_schools(iso3)
        return self._real_indicators(
            tenant_id, lga_coords, schools,
            national_internet_pct, national_mobile_pct,
        )

    async def _fetch_schools(self, iso3: str) -> list[tuple[float, float]]:
        """All (lon, lat) school points for a country from GIGA (cached)."""
        if iso3 in self._schools_cache:
            return self._schools_cache[iso3]
        url = f"{GIGA_API_HOST}/schools_location/country/{iso3}"
        headers = {
            "Authorization": f"Bearer {self._settings.giga_api_key}",
            "Accept": "application/json",
        }
        async with self._http_ctx() as client:
            resp = await client.get(url, headers=headers, timeout=120.0)
        if resp.status_code != 200:
            raise GigaItuStatsError(
                f"GIGA schools_location {iso3} {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GigaItuStatsError(f"GIGA {iso3}: non-JSON body") from exc
        rows = payload.get("data") if isinstance(payload, dict) else payload
        points: list[tuple[float, float]] = []
        for r in rows or []:
            lon, lat = r.get("longitude"), r.get("latitude")
            if lon is not None and lat is not None:
                try:
                    points.append((float(lon), float(lat)))
                except (TypeError, ValueError):
                    continue
        self._schools_cache[iso3] = points
        log.info("giga: fetched %d schools for %s", len(points), iso3)
        return points

    def _real_indicators(
        self,
        tenant_id: str,
        lga_coords: dict[str, tuple[float, float]],
        schools: list[tuple[float, float]],
        national_internet_pct: float | None = None,
        national_mobile_pct: float | None = None,
    ) -> list[SkillsIndicator]:
        """Bin real GIGA schools to LGAs. Connectivity is anchored to the real
        World Bank national ICT figures when supplied, else modelled."""
        counts: dict[str, int] = {lga: 0 for lga in lga_coords}
        for lon, lat in schools:
            lga = _nearest_lga(lon, lat, lga_coords)
            if lga is not None:
                counts[lga] += 1

        # Modelled fields reuse the mock generator (deterministic); we overwrite
        # school_count + density with REAL GIGA figures, and connectivity with
        # the REAL national ICT anchor (+ small per-LGA modulation) when given.
        modelled = {m.lga: m for m in self._mock_indicators(tenant_id, list(lga_coords))}
        out: list[SkillsIndicator] = []
        for lga, m in modelled.items():
            real_count = counts.get(lga, 0)
            youth = m.youth_population
            density = round(real_count / max(1.0, youth / 10_000), 2)

            if national_internet_pct is not None:
                # ±6pt per-LGA spread around the real national internet rate.
                net_unit = _hash_unit(tenant_id, lga, "wb_net")
                internet = max(0.5, min(99.0, national_internet_pct + (net_unit - 0.5) * 12))
                base_mob = national_mobile_pct if national_mobile_pct is not None else internet + 20
                mobile = max(internet, min(99.5, base_mob + (net_unit - 0.5) * 6))
                # Recompute learning gap from the real connectivity + density.
                density_norm = min(1.0, density / 5.0)
                gap = round(max(0.05, min(0.98,
                    (1 - internet / 100.0) * 0.4
                    + (1 - density_norm) * 0.3
                    + (1 - m.electricity_reliability) * 0.3)), 3)
                internet = round(internet, 1)
                mobile = round(mobile, 1)
            else:
                internet, mobile, gap = (
                    m.internet_coverage_pct, m.mobile_coverage_pct, m.learning_gap_index)

            out.append(SkillsIndicator(
                lga=lga,
                school_count=real_count,                 # REAL (GIGA)
                school_density_per_10k=density,          # REAL count / modelled youth
                internet_coverage_pct=internet,          # REAL anchor (WB) or modelled
                mobile_coverage_pct=mobile,              # REAL anchor (WB) or modelled
                electricity_reliability=m.electricity_reliability,  # modelled
                youth_population=youth,                   # modelled
                learning_gap_index=gap,
                source=SOURCE_GIGA,
            ))
        log.info(
            "giga: tenant=%s real school_count total=%d net_anchor=%s",
            tenant_id, sum(counts.values()), national_internet_pct,
        )
        return out

    def _http_ctx(self) -> "httpx.AsyncClient | _Borrowed":
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()

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


class _Borrowed:
    """Async-context wrapper that does NOT close an injected client (tests)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
