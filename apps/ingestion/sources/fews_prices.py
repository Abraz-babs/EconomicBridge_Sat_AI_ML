"""FEWS NET FDW market prices — the market-level overlay.

The Famine Early Warning Systems Network publishes a public, keyless data
warehouse. Unlike NBS (national + zone only) its rows are per MARKET and carry
`admin_1` (state) and `admin_2` (LGA), so where it has data it is far more
precise than a zone average.

    GET https://fdw.fews.net/api/marketpricefacts/?format=json&country=NG

COVERAGE — verified 2026-07-27, and the reason this is an OVERLAY not a base
-----------------------------------------------------------------------------
84,427 rows (66,773 priced), but the priced data concentrates in the
humanitarian north-east. For our pilots:

    Zamfara   4,639 rows, current to 2026-06-30
    Kebbi     4,105 rows, stops 2025-01-31
    Kaduna    7,844 rows, stops 2025-01-31
    Benue, Niger, Plateau, Nasarawa, FCT   ZERO priced rows

Every one of those states DOES appear in /api/market/ — 161 Nigerian markets,
all 8 pilots present. Market listings are not price data, and treating them as
coverage is the mistake that also makes WFP look usable when it is not.

GOTCHA: the API silently IGNORES unknown query params. `admin_1=Kebbi` returns
Abia rows and the entire country dump; `fnid=` returns nothing; `limit=` does
nothing. Never trust a filter here — pull the country dump and filter locally.
At ~8 MB gzipped / ~23 s on a monthly job that is cheap.

UNITS — same rule as the NBS source: convert only an explicit mass basis.
`unit_type` is one of Weight (kg / 50_kg / 100_kg), Volume (L, 30_L) or Item
(ea, 100_tubers, 60_tubers). Only Weight converts. Oils and fuel are volumes;
bread, livestock and yam-by-tuber are counts with no stated weight, so they are
skipped rather than assigned an invented one.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

import httpx

log = logging.getLogger(__name__)

API_URL = "https://fdw.fews.net/api/marketpricefacts/"
SOURCE_TAG = "fews_market_v1"

# Only these carry a mass basis; everything else is skipped.
_WEIGHT_UNIT = re.compile(r"^(?:(\d+)_)?kg$", re.I)

# FEWS product -> our canonical crop key. Deliberately aligned with the NBS
# labels in sources/nbs_food_prices.py so both sources land on one vocabulary
# and can be compared for the same crop/month.
CROP_BY_PRODUCT: dict[str, str] = {
    "Maize Grain (White)": "maize_white",
    "Maize Grain (Yellow)": "maize_yellow",
    "Rice (Milled)": "rice_local",
    "Rice (5% Broken)": "rice_imported",
    "Cowpeas (Brown)": "beans_brown",     # cowpea is the Nigerian "brown beans"
    "Cowpeas (White)": "beans_white",
    "Gari (White)": "gari_white",
    "Gari (Yellow)": "gari_yellow",
    "Sorghum (Brown)": "sorghum_brown",
    "Sorghum (White)": "sorghum_white",
    "Millet (Pearl)": "millet",
    "Groundnuts (Shelled)": "groundnut",
    "Yams": "yam",
}

# Retail is the consumer-facing price and is what NBS publishes, so mixing
# wholesale in would make the two sources incomparable.
PRICE_TYPE = "Retail"

# FEWS admin_1 -> our tenant id (only states we run).
TENANT_BY_ADMIN1: dict[str, str] = {
    "Kebbi": "kebbi",
    "Kaduna": "kaduna",
    "Zamfara": "zamfara",
    "Niger": "niger",
    "Benue": "benue",
    "Plateau": "plateau",
    "Nasarawa": "nasarawa",
    "Federal Capital Territory": "fct",
}


class FewsFetchError(RuntimeError):
    """The FDW dump could not be retrieved or parsed."""


@dataclass(frozen=True)
class MarketPrice:
    """One crop's retail price for one tenant in one month, per kg."""

    crop: str
    tenant: str
    admin_1: str
    observed_at: date
    price_ngn_per_kg: float
    markets: int          # how many market observations backed this figure


def kg_multiplier(unit: str | None, unit_type: str | None) -> float | None:
    """Factor converting a quoted price to a per-kg price, or None to skip.

    Weight units only: 'kg' -> 1, '50_kg' -> 1/50, '100_kg' -> 1/100. Volume
    and Item units have no mass basis and must not be guessed at.
    """
    if (unit_type or "").strip().lower() != "weight":
        return None
    m = _WEIGHT_UNIT.match((unit or "").strip())
    if not m:
        return None
    qty = int(m.group(1)) if m.group(1) else 1
    return 1.0 / qty if qty > 0 else None


def parse_rows(raw: list[dict], *, since: date | None = None) -> list[MarketPrice]:
    """Fold the country dump into per tenant/crop/month retail prices.

    Several markets report the same crop in a month; we take the MEDIAN across
    markets rather than the mean, so one mis-keyed outlier cannot drag a state's
    price. `markets` records how many observations stood behind the figure so a
    single-market number is not mistaken for a state-wide one.
    """
    buckets: dict[tuple[str, str, date], list[float]] = defaultdict(list)
    admins: dict[tuple[str, str, date], str] = {}

    for r in raw:
        if r.get("value") is None:
            continue
        if (r.get("price_type") or "") != PRICE_TYPE:
            continue
        if (r.get("currency") or "") != "NGN":
            continue
        tenant = TENANT_BY_ADMIN1.get((r.get("admin_1") or "").strip())
        if tenant is None:
            continue
        crop = CROP_BY_PRODUCT.get((r.get("product") or "").strip())
        if crop is None:
            continue
        mult = kg_multiplier(r.get("unit"), r.get("unit_type"))
        if mult is None:
            continue
        period = r.get("period_date")
        if not period:
            continue
        try:
            observed = date.fromisoformat(str(period)[:10])
            value = float(r["value"])
        except (ValueError, TypeError):
            continue
        if value <= 0:
            continue
        if since is not None and observed < since:
            continue
        key = (crop, tenant, observed)
        buckets[key].append(value * mult)
        admins[key] = (r.get("admin_1") or "").strip()

    out = [
        MarketPrice(
            crop=crop,
            tenant=tenant,
            admin_1=admins[(crop, tenant, observed)],
            observed_at=observed,
            price_ngn_per_kg=round(median(values), 2),
            markets=len(values),
        )
        for (crop, tenant, observed), values in buckets.items()
    ]
    out.sort(key=lambda p: (p.observed_at, p.tenant, p.crop))
    return out


class FewsPriceClient:
    """Pulls the Nigeria market-price dump and folds it to tenant/crop/month."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    def _ctx(self):
        if self._http is not None:
            from sources.copernicus import _Borrowed
            return _Borrowed(self._http)
        return httpx.AsyncClient(
            # The dump is ~8 MB gzipped and takes ~23 s; give it room.
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
        )

    async def fetch(self, *, since: date | None = None) -> list[MarketPrice]:
        async with self._ctx() as client:
            resp = await client.get(API_URL, params={"format": "json", "country": "NG"})
            if resp.status_code != 200:
                raise FewsFetchError(f"FDW {resp.status_code}: {resp.text[:200]}")
            try:
                raw = resp.json()
            except ValueError as exc:
                raise FewsFetchError(f"FDW returned non-JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise FewsFetchError(f"expected a list, got {type(raw).__name__}")
        rows = parse_rows(raw, since=since)
        log.info(
            "fews: %d raw rows -> %d tenant/crop/month prices%s",
            len(raw), len(rows), f" since {since}" if since else "",
        )
        return rows
