"""Seed 24 months of realistic crop prices into public.crop_prices.

Usage (from apps/api/ with the venv active):
    python -m scripts.seed_crop_prices

Idempotent — re-running deletes every row with `source='seed_v1'` and
re-inserts the same fixture. Real source rows (nbs_fpw, faostat, amis)
are never touched.

Baseline NGN/kg prices are anchored to NBS Food Price Watch
(approximate mid-2024 figures). Monthly variation:
  * Sinusoidal seasonal cycle (harvest months cheaper)
  * Per-region multiplier (kebbi/zamfara/niger = grain belt cheaper for
    grains; ghana/senegal = ECOWAS national-level averaging)
  * Small deterministic noise from (crop, region, month) hash so the
    seed is reproducible and the same call always produces the same
    numbers.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from datetime import date
from math import pi, sin
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402


SEED_SOURCE = "seed_v1"

# 14 West African staples + their approximate mid-2024 NGN/kg baseline
# from NBS Food Price Watch. Anchor numbers — the seasonal + regional
# adjusters scale from these.
CROPS: dict[str, float] = {
    "maize":        950.0,
    "rice":         1900.0,    # local milled rice
    "cassava":      450.0,     # peeled tuber
    "yam":          1500.0,    # white yam
    "sorghum":      820.0,
    "millet":       880.0,
    "cowpea":       1900.0,    # beans
    "groundnut":    2300.0,    # shelled
    "soybean":      1500.0,
    "tomato":       1400.0,    # high volatility
    "pepper":       2400.0,    # tatashe/rodo blend
    "onion":        1200.0,
    "plantain":     650.0,
    "sweet_potato": 600.0,
}

# Peak-season months for each crop (1-12). Prices DROP by ~25% in these
# months as harvest hits markets. Sourced from FMARD planting calendar.
HARVEST_MONTHS: dict[str, set[int]] = {
    "maize":        {9, 10, 11},      # late dry-season + early wet
    "rice":         {10, 11, 12},     # wet-season harvest
    "cassava":      {11, 12, 1, 2},   # tuber roughly all year, peak dry
    "yam":          {9, 10, 11, 12},  # tuber, dry-season harvest
    "sorghum":      {10, 11, 12},
    "millet":       {9, 10, 11},
    "cowpea":       {10, 11, 12},
    "groundnut":    {10, 11, 12},
    "soybean":      {10, 11, 12},
    "tomato":       {2, 3, 4, 11, 12},  # two-season planting
    "pepper":       {2, 3, 4, 11, 12},
    "onion":        {3, 4, 5},
    "plantain":     {6, 7, 8, 9},    # wet-season fruiting
    "sweet_potato": {10, 11, 12},
}

# Per-region price multiplier vs the national baseline. Grain belt
# (kebbi/zamfara/niger/kaduna) is cheaper for cereals; FCT + plateau
# inland transport adds cost; ghana + senegal as ECOWAS national-
# averaged proxies sit close to baseline.
REGION_FACTORS: dict[str, float] = {
    "kebbi":    0.85,
    "benue":    0.95,
    "plateau":  1.05,
    "kaduna":   0.90,
    "niger":    0.92,
    "zamfara":  0.88,
    "nasarawa": 0.98,
    "fct":      1.15,    # capital premium
    "ghana":    1.08,    # GHS-pegged proxy
    "senegal":  1.10,    # CFA-pegged proxy
}


@dataclass(frozen=True, slots=True)
class PriceRow:
    crop: str
    region: str
    observed_at: date
    price_ngn_per_kg: float


def _hash_noise(crop: str, region: str, ym: int) -> float:
    """Deterministic small noise factor in [-0.06, +0.06]."""
    h = hashlib.md5(f"{crop}|{region}|{ym}".encode()).digest()
    return ((int.from_bytes(h[:2], "big") % 121) - 60) / 1000.0


def _seasonal_factor(crop: str, month: int) -> float:
    """Sinusoidal seasonality + harvest dip."""
    base = 1.0 + 0.08 * sin(2 * pi * ((month - 1) / 12.0))
    if month in HARVEST_MONTHS.get(crop, set()):
        base *= 0.78
    return base


def _months_back(n: int) -> list[date]:
    """Return the last `n` month-start dates, oldest first."""
    today = date.today()
    out: list[date] = []
    for back in range(n - 1, -1, -1):
        m = today.month - back
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        out.append(date(y, m, 1))
    return out


def build_rows(months: int = 24) -> list[PriceRow]:
    """Build the canonical (crop × region × month) seed set."""
    rows: list[PriceRow] = []
    for ym_date in _months_back(months):
        ym_key = ym_date.year * 100 + ym_date.month
        for crop, baseline in CROPS.items():
            seasonal = _seasonal_factor(crop, ym_date.month)
            for region, region_mult in REGION_FACTORS.items():
                noise = _hash_noise(crop, region, ym_key)
                price = baseline * region_mult * seasonal * (1 + noise)
                rows.append(PriceRow(
                    crop=crop, region=region,
                    observed_at=ym_date,
                    price_ngn_per_kg=round(price, 2),
                ))
    return rows


async def seed() -> int:
    """Replace all seed rows with a fresh canonical set. Returns count inserted."""
    factory = get_session_factory()
    rows = build_rows()

    async with factory() as session:
        await session.execute(
            text("DELETE FROM public.crop_prices WHERE source = :src"),
            {"src": SEED_SOURCE},
        )
        for row in rows:
            await session.execute(
                text(
                    """
                    INSERT INTO public.crop_prices
                        (crop, region, observed_at, price_ngn_per_kg, source)
                    VALUES (:crop, :region, :observed_at, :price, :source)
                    """
                ),
                {
                    "crop": row.crop, "region": row.region,
                    "observed_at": row.observed_at,
                    "price": row.price_ngn_per_kg,
                    "source": SEED_SOURCE,
                },
            )
        await session.commit()
    return len(rows)


async def main() -> None:
    n = await seed()
    print(f"seeded {n} crop_prices rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
