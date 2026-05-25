"""Seed deterministic skills_indicators rows for all 10 pilot tenants.

Internet coverage anchors calibrated against ITU Africa 2024 + UNICEF
GIGA mapping where school-level data is published:

  FCT          65  (capital — best fixed + mobile broadband)
  ghana        48  (national avg; Accra raises the floor)
  senegal      42  (Dakar + Saint-Louis well-covered)
  kaduna       35  (commercial — university towns help)
  nasarawa     30  (FCT spillover)
  benue        28  (river belt; Makurdi pulls average up)
  plateau      26  (Jos has fibre; rural plateau drops it)
  niger        18  (sparse, hydroelectric corridors)
  kebbi        12  (deep rural northern)
  zamfara      10  (similar to kebbi, conflict-impacted)

School density anchored to UNICEF GIGA benchmark of ~4 primary + ~1.5
secondary per 10k pop for developed regions, scaled down for our pilots.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
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


# (internet_pct_anchor, spread, school_density_anchor, electricity_anchor)
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
    school_count: int
    school_density_per_10k: float
    internet_coverage_pct: float
    mobile_coverage_pct: float
    electricity_reliability: float
    youth_population: int
    learning_gap_index: float


def _hash_unit(tenant_id: str, lga: str, salt: str) -> float:
    """Deterministic [0, 1) draw from (tenant, lga, salt)."""
    h = hashlib.md5(
        f"{tenant_id}|{lga}|{salt}".encode(), usedforsecurity=False,
    ).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


def _rows_for(tenant_id: str) -> list[SeedRow]:
    centroid = TENANT_CENTROIDS.get(tenant_id, (0.0, 0.0))
    profile = TENANT_SKILLS_PROFILE.get(tenant_id, (25.0, 10.0, 2.5, 0.55))
    net_anchor, net_spread, density_anchor, power_anchor = profile
    lgas = LGA_POOL.get(tenant_id, [f"{tenant_id} Region 1"])
    rows: list[SeedRow] = []
    for i, lga in enumerate(lgas):
        # Same 8-direction fan as Modules 02 + 06 — overlays cleanly.
        angle_rad = math.radians((i * 360 / max(len(lgas), 1)) % 360)
        radius = 0.4 + (i % 3) * 0.18
        lon = centroid[0] + math.cos(angle_rad) * radius
        lat = centroid[1] + math.sin(angle_rad) * radius * 0.85

        net_unit = _hash_unit(tenant_id, lga, "net")
        internet_pct = max(0.5, min(98.0,
            net_anchor + (net_unit - 0.5) * net_spread * 2
        ))

        # Mobile coverage runs ~20-30pts above internet (2G blanket is wider).
        mob_unit = _hash_unit(tenant_id, lga, "mob")
        mobile_pct = max(5.0, min(99.0,
            internet_pct + 18 + mob_unit * 18
        ))

        density_unit = _hash_unit(tenant_id, lga, "density")
        density = max(0.3,
            density_anchor + (density_unit - 0.5) * density_anchor * 0.6
        )

        power_unit = _hash_unit(tenant_id, lga, "power")
        electricity = max(0.10, min(0.98,
            power_anchor + (power_unit - 0.5) * 0.25
        ))

        # Youth pop = 40-50% of total pop in West Africa.
        pop_unit = _hash_unit(tenant_id, lga, "pop")
        youth_pop = int(18_000 + pop_unit * 130_000)
        school_count = max(1, int(density * (youth_pop / 10_000)))

        # Learning gap composite — 1 means no infra, 0 means fully served.
        internet_norm = internet_pct / 100.0
        density_norm = min(1.0, density / 5.0)
        gap = max(0.05, min(0.98,
            (1 - internet_norm) * 0.4
            + (1 - density_norm) * 0.3
            + (1 - electricity) * 0.3
        ))

        rows.append(SeedRow(
            tenant_id=tenant_id,
            lga=lga,
            lon=lon, lat=lat,
            school_count=school_count,
            school_density_per_10k=round(density, 2),
            internet_coverage_pct=round(internet_pct, 1),
            mobile_coverage_pct=round(mobile_pct, 1),
            electricity_reliability=round(electricity, 3),
            youth_population=youth_pop,
            learning_gap_index=round(gap, 3),
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
                text("DELETE FROM skills_indicators WHERE source = :src"),
                {"src": SEED_SOURCE},
            )
            for r in _rows_for(tenant_id):
                await session.execute(
                    text(
                        """
                        INSERT INTO skills_indicators (
                            tenant_id, lga, location,
                            school_count, school_density_per_10k,
                            internet_coverage_pct, mobile_coverage_pct,
                            electricity_reliability, youth_population,
                            learning_gap_index, observed_at, source
                        ) VALUES (
                            :tenant_id, :lga,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            :school_count, :density, :net_pct, :mob_pct,
                            :power, :youth_pop, :gap, :observed_at, :source
                        )
                        """
                    ),
                    {
                        "tenant_id": r.tenant_id, "lga": r.lga,
                        "lon": r.lon, "lat": r.lat,
                        "school_count": r.school_count,
                        "density": r.school_density_per_10k,
                        "net_pct": r.internet_coverage_pct,
                        "mob_pct": r.mobile_coverage_pct,
                        "power": r.electricity_reliability,
                        "youth_pop": r.youth_population,
                        "gap": r.learning_gap_index,
                        "observed_at": today,
                        "source": SEED_SOURCE,
                    },
                )
                total += 1
        await session.commit()
    return total


async def main() -> None:
    n = await seed()
    print(f"seeded {n} skills_indicators rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
