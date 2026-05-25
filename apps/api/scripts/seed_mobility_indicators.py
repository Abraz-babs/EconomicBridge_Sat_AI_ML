"""Seed deterministic mobility_indicators rows for all 10 pilot tenants.

Cost-of-living anchors are calibrated against NBS Selected Food + Non-
Food Items 2024 baseline + plausible regional intuitions:

  FCT       150  (capital premium)
  ghana/sen 108-114 (ECOWAS national-level averages)
  benue     105  (river-belt; trade hub but rural)
  plateau   102  (Jos plateau; cooler climate, mid-priced)
  nasarawa  100  (FCT spillover baseline)
  kaduna     94  (commercial centre but rural premium balance)
  niger      85  (rural)
  kebbi      78  (rural northern grain belt)
  zamfara    76  (similar to kebbi, slightly more conflict-impacted)

Income opportunity + displacement capacity scale inversely with rural-
ness — capital regions absorb displaced populations easier; remote
states have less formal-sector capacity but more land.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name  # noqa: E402


SEED_SOURCE = "seed_v1"


# Per-tenant cost-of-living anchor + LGA spread (how wide the per-LGA
# cost variation is around the anchor). Capitals have wider spreads
# (downtown vs outskirts); rural states tighter.
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
class SeedRow:
    tenant_id: str
    lga: str
    lon: float
    lat: float
    cost_of_living_index: float
    avg_household_income_ngn: int
    income_opportunity_score: float
    displacement_capacity_index: float
    population: int


def _hash_unit(tenant_id: str, lga: str, salt: str) -> float:
    """Deterministic [0, 1) draw from (tenant, lga, salt)."""
    h = hashlib.md5(
        f"{tenant_id}|{lga}|{salt}".encode(), usedforsecurity=False,
    ).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


def _rows_for(tenant_id: str) -> list[SeedRow]:
    centroid = TENANT_CENTROIDS.get(tenant_id, (0.0, 0.0))
    col_anchor, col_spread = TENANT_COL_PROFILE.get(tenant_id, (100.0, 12.0))
    lgas = LGA_POOL.get(tenant_id, [f"{tenant_id} Region 1"])
    rows: list[SeedRow] = []
    for i, lga in enumerate(lgas):
        # Deterministic LGA spread around tenant centroid (same 8-direction
        # fan we used for aid_coordination so the maps overlay cleanly).
        import math
        angle_rad = math.radians((i * 360 / max(len(lgas), 1)) % 360)
        radius = 0.4 + (i % 3) * 0.18
        lon = centroid[0] + math.cos(angle_rad) * radius
        lat = centroid[1] + math.sin(angle_rad) * radius * 0.85

        col_unit = _hash_unit(tenant_id, lga, "col")
        col_index = col_anchor + (col_unit - 0.5) * col_spread * 2

        # Income roughly tracks cost of living, with noise. ~ NGN/month.
        # National median household income ~ 110_000 NGN/month (NBS 2024).
        income_unit = _hash_unit(tenant_id, lga, "income")
        avg_income = int(
            45_000 + (col_index / 100.0) * 95_000 + income_unit * 35_000
        )

        # Opportunity score: capital regions higher, rural lower. Strongly
        # correlated with COL but also has independent variation (small
        # rural towns can have surprising agricultural opportunity).
        opp_unit = _hash_unit(tenant_id, lga, "opportunity")
        opportunity = max(0.05, min(0.95,
            0.20 + (col_index - 70) / 100 * 0.50 + (opp_unit - 0.5) * 0.20
        ))

        # Displacement capacity: capacity to ABSORB displaced people.
        # Inverse of overcrowding × proportional to available services.
        cap_unit = _hash_unit(tenant_id, lga, "capacity")
        capacity = max(0.10, min(0.92,
            0.30 + (col_index - 70) / 200 + (cap_unit - 0.5) * 0.30
        ))

        # Population — modest ranges; WorldPop ingest replaces this later.
        pop_unit = _hash_unit(tenant_id, lga, "pop")
        population = int(40_000 + pop_unit * 280_000)

        rows.append(SeedRow(
            tenant_id=tenant_id,
            lga=lga,
            lon=lon, lat=lat,
            cost_of_living_index=round(col_index, 1),
            avg_household_income_ngn=avg_income,
            income_opportunity_score=round(opportunity, 3),
            displacement_capacity_index=round(capacity, 3),
            population=population,
        ))
    return rows


async def seed() -> int:
    factory = get_session_factory()
    total = 0
    today = date.today()
    async with factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            await session.execute(
                text("DELETE FROM mobility_indicators WHERE source = :src"),
                {"src": SEED_SOURCE},
            )
            for r in _rows_for(tenant_id):
                await session.execute(
                    text(
                        """
                        INSERT INTO mobility_indicators (
                            tenant_id, lga, location,
                            cost_of_living_index, avg_household_income_ngn,
                            income_opportunity_score, displacement_capacity_index,
                            population, observed_at, source
                        ) VALUES (
                            :tenant_id, :lga,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            :col, :income, :opp, :cap, :pop, :observed_at, :source
                        )
                        """
                    ),
                    {
                        "tenant_id": r.tenant_id, "lga": r.lga,
                        "lon": r.lon, "lat": r.lat,
                        "col": r.cost_of_living_index,
                        "income": r.avg_household_income_ngn,
                        "opp": r.income_opportunity_score,
                        "cap": r.displacement_capacity_index,
                        "pop": r.population,
                        "observed_at": today,
                        "source": SEED_SOURCE,
                    },
                )
                total += 1
        await session.commit()
    return total


async def main() -> None:
    n = await seed()
    print(f"seeded {n} mobility_indicators rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
