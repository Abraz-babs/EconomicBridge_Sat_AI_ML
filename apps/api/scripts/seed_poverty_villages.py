"""Seed deterministic poverty_villages rows for all 10 pilot tenants.

Python port of apps/frontend/src/data/povertySeed.ts. Same hash + RNG
seed produces the same villages so frontend/backend stay aligned
during the seed→live data transition.

Usage (from apps/api/ with the venv active):
    python -m scripts.seed_poverty_villages

Idempotent: re-runs delete `source='seed_v1'` rows and re-insert.
Live source rows (viirs_v2, worldpop_v1, dhs_v1, …) are never touched.
NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.lga_geo import centroid_for  # noqa: E402
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name  # noqa: E402


SEED_SOURCE = "seed_v1"


# Per-tenant centroid (mirrors apps/frontend/src/data/tenants.ts)
TENANT_CENTROIDS: dict[str, tuple[float, float]] = {
    "kebbi":    (4.55, 12.00),
    "benue":    (8.85, 7.20),
    "plateau":  (9.25, 9.45),
    "kaduna":   (8.15, 10.40),
    "niger":    (5.50, 10.30),
    "zamfara":  (6.50, 12.30),
    "nasarawa": (8.40, 8.85),
    "fct":      (7.49, 9.06),
    "ghana":    (-1.10, 7.95),
    "senegal":  (-14.45, 14.50),
}


LGA_POOL: dict[str, list[str]] = {
    "kebbi":   ["Argungu", "Birnin Kebbi", "Dandi", "Gwandu", "Jega", "Yauri", "Zuru", "Bunza"],
    "benue":   ["Agatu", "Logo", "Tarka", "Guma", "Vandeikya", "Otukpo", "Apa", "Buruku"],
    "plateau": ["Bassa", "Riyom", "Bokkos", "Jos North", "Pankshin", "Wase", "Shendam", "Mangu"],
    "kaduna":  ["Birnin Gwari", "Zangon Kataf", "Kafanchan", "Jaba", "Kaura", "Chikun", "Igabi", "Sabon Gari"],
    "niger":   ["Shiroro", "Kontagora", "Mariga", "Borgu", "Lapai", "Agaie", "Suleja", "Bida"],
    "zamfara": ["Maru", "Maradun", "Anka", "Bukkuyum", "Gusau", "Kaura Namoda", "Tsafe", "Talata Mafara"],
    "nasarawa":["Akwanga", "Wamba", "Doma", "Karu", "Keffi", "Lafia", "Awe", "Kokona"],
    "fct":     ["Abaji", "Bwari", "Gwagwalada", "Kuje", "Kwali", "AMAC"],
    "ghana":   ["Pusiga", "Garu-Tempane", "Bawku", "Tamale", "Bolgatanga", "Wa", "Sunyani", "Kumasi"],
    "senegal": ["Sédhiou", "Kolda", "Tambacounda", "Kédougou", "Matam", "Saint-Louis", "Diourbel", "Kaffrine"],
}


@dataclass(frozen=True, slots=True)
class SeedVillage:
    tenant_id: str
    settlement_name: str
    lga: str
    lon: float
    lat: float
    poverty_score: float
    population: int
    households_unreached: int
    nightlight_dimness: float
    has_dhs_data: bool


def _djb2(s: str) -> int:
    """Same hash function as the frontend (povertySeed.ts) so the
    backend produces the same villages."""
    h = 5381
    for c in s:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return abs(h)


class _Rng:
    """Same linear congruential generator as the frontend."""
    def __init__(self, seed: int) -> None:
        self.state = seed or 1

    def next(self) -> float:
        self.state = (self.state * 1664525 + 1013904223) & 0xFFFFFFFF
        if self.state >= 0x80000000:
            self.state -= 0x100000000
        return ((self.state & 0xFFFFFFFF) % 100000) / 100000.0


def _villages_for(tenant_id: str) -> list[SeedVillage]:
    lgas = LGA_POOL.get(
        tenant_id,
        [f"{tenant_id} Region 1", f"{tenant_id} Region 2"],
    )
    rng = _Rng(_djb2(tenant_id))
    count = 8 + int(rng.next() * 4)   # 8..11 villages

    out: list[SeedVillage] = []
    for i in range(count):
        lga = lgas[i % len(lgas)]
        # Jitter around the LGA centroid (services/lga_geo.py) so each
        # synthetic settlement lands near its parent LGA's HQ town instead
        # of drifting up to ~1° away from the tenant centroid, which
        # previously placed villages in neighbouring states. Unknown
        # tenants (pre-pilot) fall back to (0, 0) — a deliberate sentinel
        # so a mis-routed dashboard call lands somewhere obviously wrong.
        try:
            lga_lon, lga_lat = centroid_for(tenant_id, lga)
        except KeyError:
            lga_lon, lga_lat = 0.0, 0.0
        lon_jitter = (rng.next() - 0.5) * 0.25
        lat_jitter = (rng.next() - 0.5) * 0.20
        lon = lga_lon + lon_jitter
        lat = lga_lat + lat_jitter
        poverty = min(0.99, 0.35 + rng.next() * 0.6)
        population = 800 + int(rng.next() * 6_000)
        # Same per-row hh_unreached as the frontend: pop * (0.1..0.45) / 4
        unreached = int(population * (0.10 + rng.next() * 0.35) / 4)
        dimness = 0.40 + rng.next() * 0.55
        has_dhs = rng.next() > 0.35

        out.append(SeedVillage(
            tenant_id=tenant_id,
            settlement_name=f"{lga} settlement {i + 1}",
            lga=lga,
            lon=lon, lat=lat,
            poverty_score=poverty,
            population=population,
            households_unreached=unreached,
            nightlight_dimness=dimness,
            has_dhs_data=has_dhs,
        ))
    return out


async def seed() -> int:
    """Replace all seed rows with a fresh canonical set. Returns count."""
    factory = get_session_factory()
    total = 0

    async with factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            await session.execute(
                text("DELETE FROM poverty_villages WHERE source = :src"),
                {"src": SEED_SOURCE},
            )
            for v in _villages_for(tenant_id):
                await session.execute(
                    text(
                        """
                        INSERT INTO poverty_villages (
                            tenant_id, settlement_name, lga, location,
                            poverty_score, population, households_unreached,
                            nightlight_dimness, has_dhs_data, source
                        ) VALUES (
                            :tenant_id, :settlement_name, :lga,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            :poverty_score, :population, :hh_unreached,
                            :dimness, :has_dhs, :source
                        )
                        """
                    ),
                    {
                        "tenant_id": v.tenant_id,
                        "settlement_name": v.settlement_name,
                        "lga": v.lga,
                        "lon": v.lon, "lat": v.lat,
                        "poverty_score": v.poverty_score,
                        "population": v.population,
                        "hh_unreached": v.households_unreached,
                        "dimness": v.nightlight_dimness,
                        "has_dhs": v.has_dhs_data,
                        "source": SEED_SOURCE,
                    },
                )
                total += 1
        await session.commit()
    return total


async def main() -> None:
    n = await seed()
    print(f"seeded {n} poverty_villages rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
