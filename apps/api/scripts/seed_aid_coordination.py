"""Seed deterministic aid_agencies + aid_coverage rows for Module 02.

Python port of apps/frontend/src/data/aidCoordinationSeed.ts. Same
djb2 + LCG so the dashboard renders the same agencies × LGAs grid
under the new DB-backed path as it did under the old frontend seed.

Usage (from apps/api/ with the venv active):
    python -m scripts.seed_aid_coordination

Idempotent:
  * `public.aid_agencies` is populated via UPSERT on slug.
  * `tenant_<id>.aid_coverage` rows tagged `source='seed_v1'` are
    fully replaced; rows from real sources (wfp_scope_v1, etc.) are
    never touched.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name  # noqa: E402


SEED_SOURCE = "seed_v1"


# Global agency registry. `country` is the SCOPE: 'international' agencies
# operate everywhere; national agencies only appear in their own country
# (a Nigerian agency like NEMA must never show up in Ghana/Senegal).
AGENCY_REGISTRY: list[dict[str, str]] = [
    {"slug": "wfp",         "name": "World Food Programme",      "sector": "food security",    "country": "international"},
    {"slug": "unhcr",       "name": "UNHCR",                       "sector": "displacement",     "country": "international"},
    {"slug": "unicef",      "name": "UNICEF",                      "sector": "child welfare",    "country": "international"},
    {"slug": "msf",         "name": "Médecins Sans Frontières",    "sector": "medical",          "country": "international"},
    {"slug": "save_kids",   "name": "Save the Children",           "sector": "child welfare",    "country": "international"},
    {"slug": "oxfam",       "name": "Oxfam",                       "sector": "food security",    "country": "international"},
    {"slug": "mercy",       "name": "Mercy Corps",                 "sector": "livelihoods",      "country": "international"},
    {"slug": "norwegian",   "name": "Norwegian Refugee Council",   "sector": "displacement",     "country": "international"},
    # National agencies — scoped to their own country only.
    {"slug": "red_cross",   "name": "Nigerian Red Cross",          "sector": "emergency relief", "country": "nigeria"},
    {"slug": "nema",        "name": "NEMA",                        "sector": "disaster relief",  "country": "nigeria"},
    {"slug": "nadmo",       "name": "NADMO (Ghana)",               "sector": "disaster relief",  "country": "ghana"},
    {"slug": "gh_red_cross", "name": "Ghana Red Cross Society",    "sector": "emergency relief", "country": "ghana"},
    {"slug": "sn_red_cross", "name": "Croix-Rouge sénégalaise",    "sector": "emergency relief", "country": "senegal"},
    {"slug": "sn_anacim",   "name": "ANACIM (Senegal)",            "sector": "disaster relief",  "country": "senegal"},
]

# Tenant → country, so each tenant only draws from international + its own
# national agencies. Nigerian states all map to 'nigeria'.
TENANT_COUNTRY: dict[str, str] = {
    "kebbi": "nigeria", "benue": "nigeria", "plateau": "nigeria",
    "kaduna": "nigeria", "niger": "nigeria", "zamfara": "nigeria",
    "nasarawa": "nigeria", "fct": "nigeria", "ghana": "ghana", "senegal": "senegal",
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
class SeedCoverage:
    tenant_id: str
    agency_slug: str
    lga: str
    beneficiaries_served: int


def _djb2(s: str) -> int:
    h = 5381
    for c in s:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return abs(h)


class _Rng:
    def __init__(self, seed: int) -> None:
        self.state = seed or 1

    def next(self) -> float:
        self.state = (self.state * 1664525 + 1013904223) & 0xFFFFFFFF
        if self.state >= 0x80000000:
            self.state -= 0x100000000
        return ((self.state & 0xFFFFFFFF) % 100000) / 100000.0


def _coverage_for(tenant_id: str) -> list[SeedCoverage]:
    """Match the frontend's coordinationStatsFor coverage pick."""
    lgas = LGA_POOL.get(tenant_id, [f"{tenant_id} R1", f"{tenant_id} R2"])
    rng = _Rng(_djb2(tenant_id))
    agency_count = 5 + int(rng.next() * 4)  # 5..8

    # Scope to international + this tenant's own national agencies, so e.g.
    # NEMA (Nigeria) never appears in Ghana. Then sort by hash(tenant+slug)
    # and pick the first N for a stable per-tenant selection.
    country = TENANT_COUNTRY.get(tenant_id, "nigeria")
    pool = [a for a in AGENCY_REGISTRY if a["country"] in ("international", country)]
    shuffled = sorted(pool, key=lambda a: _djb2(tenant_id + a["slug"]))
    picked = shuffled[:agency_count]

    coverage: list[SeedCoverage] = []
    for a in picked:
        lga_count = 2 + int(rng.next() * 4)  # 2..5
        covered: list[str] = []
        for _ in range(lga_count):
            if len(covered) >= len(lgas):
                break
            idx = int(rng.next() * len(lgas))
            if lgas[idx] not in covered:
                covered.append(lgas[idx])
        beneficiaries = 1_500 + int(rng.next() * 18_000)
        for lga in covered:
            coverage.append(SeedCoverage(
                tenant_id=tenant_id,
                agency_slug=a["slug"],
                lga=lga,
                # Spread beneficiaries roughly equally across an agency's LGAs.
                beneficiaries_served=beneficiaries // max(len(covered), 1),
            ))
    return coverage


async def _seed_agencies(session) -> None:
    """UPSERT the 10 known agencies — slug is the natural key."""
    for a in AGENCY_REGISTRY:
        await session.execute(
            text(
                """
                INSERT INTO public.aid_agencies (slug, name, sector, country)
                VALUES (:slug, :name, :sector, :country)
                ON CONFLICT (slug) DO UPDATE
                  SET name = EXCLUDED.name,
                      sector = EXCLUDED.sector,
                      country = EXCLUDED.country
                """
            ),
            a,
        )


async def seed() -> int:
    factory = get_session_factory()
    total_coverage = 0
    today = date.today()
    last_active = today - timedelta(days=14)   # ~2 weeks back

    async with factory() as session:
        await _seed_agencies(session)

        for tenant_id in sorted(PILOT_TENANT_IDS):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            await session.execute(
                text("DELETE FROM aid_coverage WHERE source = :src"),
                {"src": SEED_SOURCE},
            )
            for cov in _coverage_for(tenant_id):
                await session.execute(
                    text(
                        """
                        INSERT INTO aid_coverage (
                            tenant_id, agency_slug, lga,
                            beneficiaries_served, last_active_at, source
                        ) VALUES (
                            :tenant_id, :agency_slug, :lga,
                            :beneficiaries, :last_active, :source
                        )
                        """
                    ),
                    {
                        "tenant_id": cov.tenant_id,
                        "agency_slug": cov.agency_slug,
                        "lga": cov.lga,
                        "beneficiaries": cov.beneficiaries_served,
                        "last_active": last_active,
                        "source": SEED_SOURCE,
                    },
                )
                total_coverage += 1

        await session.commit()
    return total_coverage


async def main() -> None:
    n = await seed()
    print(f"seeded {len(AGENCY_REGISTRY)} agencies + {n} coverage rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
