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
from services.lga_geo import centroid_for  # noqa: E402
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


# Nigerian pilots carry a Naira figure; ECOWAS pilots are USD-only (the
# dashboard shows ₦X ($Y) for Nigeria, $Y for Ghana/Senegal).
NIGERIAN_TENANTS = frozenset({
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "nasarawa", "fct",
})
# Seed-only indicative FX (Naira per USD, ~2026). The live worldbank_v1 rows
# carry real per-currency figures from the World Bank and override seed in the
# source-preference dedup; this constant only shapes the synthetic baseline.
SEED_NGN_PER_USD = 1600.0


@dataclass(frozen=True, slots=True)
class SeedRow:
    tenant_id: str
    lga: str
    lon: float
    lat: float
    cost_of_living_index: float
    avg_household_income_ngn: int | None
    avg_household_income_usd: int
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
    col_anchor, col_spread = TENANT_COL_PROFILE.get(tenant_id, (100.0, 12.0))
    lgas = LGA_POOL.get(tenant_id, [f"{tenant_id} Region 1"])
    rows: list[SeedRow] = []
    for lga in lgas:
        # Real per-LGA centroid (HQ town) from services/lga_geo.py — replaces
        # the previous 8-direction synthetic fan that could spill across
        # state lines (e.g. an FCT LGA landing in southern Kaduna).
        lon, lat = centroid_for(tenant_id, lga)

        col_unit = _hash_unit(tenant_id, lga, "col")
        col_index = col_anchor + (col_unit - 0.5) * col_spread * 2

        # Income roughly tracks cost of living, with noise. The base figure is
        # modelled in NGN/month (national median ~110_000 NGN, NBS 2024); USD
        # is derived via the seed FX. Nigerian tenants keep the NGN figure;
        # ECOWAS tenants are USD-only (NGN set to None).
        income_unit = _hash_unit(tenant_id, lga, "income")
        avg_income_ngn = int(
            45_000 + (col_index / 100.0) * 95_000 + income_unit * 35_000
        )
        avg_income_usd = int(avg_income_ngn / SEED_NGN_PER_USD)
        is_nigerian = tenant_id in NIGERIAN_TENANTS

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
            avg_household_income_ngn=avg_income_ngn if is_nigerian else None,
            avg_household_income_usd=avg_income_usd,
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
                            avg_household_income_usd,
                            income_opportunity_score, displacement_capacity_index,
                            population, observed_at, source
                        ) VALUES (
                            :tenant_id, :lga,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            :col, :income_ngn, :income_usd, :opp, :cap, :pop,
                            :observed_at, :source
                        )
                        """
                    ),
                    {
                        "tenant_id": r.tenant_id, "lga": r.lga,
                        "lon": r.lon, "lat": r.lat,
                        "col": r.cost_of_living_index,
                        "income_ngn": r.avg_household_income_ngn,
                        "income_usd": r.avg_household_income_usd,
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
