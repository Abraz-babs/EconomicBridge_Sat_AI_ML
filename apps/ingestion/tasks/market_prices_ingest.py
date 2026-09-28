"""Monthly World Bank Real Time Prices ingest — food and petrol by market.

Writes public.market_prices (migration 0059) for the Mobility Compass's
"what it costs to live and to move". Source: World Bank DECDG Real Time
Prices for Nigeria on HDX (dataset "nigeria-real-time-prices", CC BY 4.0),
refreshed by the World Bank every few weeks.

TWO KINDS OF NUMBER, KEPT APART
-------------------------------
Each item in the file has a surveyed column (the price actually collected at
the market that month, blank when nobody surveyed) and the World Bank's model
estimates for every month (open / high / low / close). They differ: in June
2026 maize at Kaura Namoda was surveyed at ₦382/kg while the model's close
was ₦515. So both are stored, tagged apart:

    wb_rtp_estimate_v1   the month's CLOSE estimate — a continuous series,
                         which is what the page plots, labelled as modelled
    wb_rtp_survey_v1     the surveyed price, where one exists — kept so the
                         page can say when a market was last surveyed

Measured 2026-09-28: no market in the file has had petrol surveyed since
January 2023, and in 2023 the petrol estimates run at about half the pump
price. The page therefore shows petrol for the last 12 months only, as an
estimate, never as a headline.

Rows kept: markets inside the pilot states (Kaura Namoda, Gwandu, Giwa,
Saminaka), the geopolitical-zone averages, and the all-market average.
UPSERT, NEVER DELETE: the model revises past months, and a revision updates
the row (the retention trigger keeps the old value).
"""
from __future__ import annotations

import csv
import io
import logging
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import text

from db import get_session_factory

log = logging.getLogger(__name__)

RUN_SOURCE = "wb_rtp_v1"
ESTIMATE = "wb_rtp_estimate_v1"
SURVEY = "wb_rtp_survey_v1"

_DATASET = "https://data.humdata.org/dataset/73009422-8e57-41a4-ad24-d77f9405accb/resource"
FOOD_CSV = f"{_DATASET}/3b8a3d72-4229-4c35-99c1-8adfe6057c96/download/real-time-food-prices-for-nigeria.csv"
ENERGY_CSV = f"{_DATASET}/a8dbee76-02d2-443e-91d1-a3978826bafd/download/real-time-energy-prices-for-nigeria.csv"

# File column -> (item, unit). Only per-kg ("_fao") food columns: the plain
# food columns are priced per local measure that differs by market.
FOOD_ITEMS = {
    "maize_fao": ("maize", "kg"), "sorghum_fao": ("sorghum", "kg"),
    "rice_fao": ("rice", "kg"), "gari_fao": ("gari", "kg"),
}
ENERGY_ITEMS = {"fuel_petrol_gasoline": ("petrol", "litre")}

# adm1 values worth keeping: the pilot states the file covers, plus the
# averages a state without a market falls back to.
KEEP_ADM1 = frozenset({
    "Kebbi", "Zamfara", "Kaduna", "Niger", "Benue", "Plateau", "Nasarawa",
    "FCT", "Abuja", "Federal Capital Territory",
    "Geopolitical Zone", "Market Average",
})

UPSERT = text("""
    INSERT INTO public.market_prices
        (item, unit, market, adm1, adm2, observed_at, price_ngn, source)
    VALUES (:item, :unit, :market, :adm1, :adm2, :observed_at, :price, :source)
    ON CONFLICT (item, adm1, market, observed_at, source) DO UPDATE SET
        unit = EXCLUDED.unit, adm2 = EXCLUDED.adm2,
        price_ngn = EXCLUDED.price_ngn, loaded_at = NOW()
    WHERE (market_prices.unit, market_prices.adm2, market_prices.price_ngn)
          IS DISTINCT FROM (EXCLUDED.unit, EXCLUDED.adm2, EXCLUDED.price_ngn)
""")


@dataclass
class IngestResult:
    rows: int = 0
    series: set[tuple[str, str, str]] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def _price(v: str | None) -> float | None:
    try:
        p = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return p if p is not None and p > 0 else None


def parse_rtp(lines: Iterable[str], items: dict[str, tuple[str, str]]) -> Iterator[dict]:
    """Rows of one RTP file -> upsert dicts (estimate and, where present, survey).

    Pure: takes the CSV text line by line, so it is testable without a network.
    Skips rows outside KEEP_ADM1, rows the World Bank interpolated in space
    (no market there), and non-positive or blank prices.
    """
    for row in csv.DictReader(lines):
        adm1 = (row.get("adm1_name") or "").strip()
        if adm1 not in KEEP_ADM1 or (row.get("spatially_interpolated") or "0").strip() not in ("0", ""):
            continue
        try:
            observed = date.fromisoformat((row.get("DATES") or "")[:10])
        except ValueError:
            continue
        market = (row.get("mkt_name") or "").strip()
        if not market:
            continue
        base = {"market": market, "adm1": adm1, "adm2": (row.get("adm2_name") or "").strip() or None,
                "observed_at": observed}
        for col, (item, unit) in items.items():
            est = _price(row.get(f"c_{col}"))
            if est is not None:
                yield {**base, "item": item, "unit": unit, "price": round(est, 2), "source": ESTIMATE}
            obs = _price(row.get(col))
            if obs is not None:
                yield {**base, "item": item, "unit": unit, "price": round(obs, 2), "source": SURVEY}


async def _download(client: httpx.AsyncClient, url: str) -> tempfile.SpooledTemporaryFile:
    """Stream a CSV to a spooled temp file (the food file is ~35 MB)."""
    buf = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    async with client.stream("GET", url, follow_redirects=True) as r:
        r.raise_for_status()
        async for chunk in r.aiter_bytes():
            buf.write(chunk)
    buf.seek(0)
    return buf


async def _record_run(session, *, written: int, started_at: datetime, error: str | None) -> None:
    await session.execute(text("""
        INSERT INTO public.ingestion_runs (
            id, source, tenant_id, trigger, started_at, finished_at,
            status, records_ingested, error_message, dry_run
        ) VALUES (
            :id, :source, 'public', 'scheduled', :started_at, NOW(),
            :status, :written, :error, FALSE
        )
    """), {
        "id": uuid4(), "source": RUN_SOURCE, "started_at": started_at, "written": written,
        "status": "failed" if error else "succeeded", "error": error[:500] if error else None,
    })


async def ingest() -> IngestResult:
    started = datetime.now(timezone.utc)
    result = IngestResult()
    factory = get_session_factory()
    async with httpx.AsyncClient(timeout=180) as client, factory() as session:
        for label, url, items in (("food", FOOD_CSV, FOOD_ITEMS), ("energy", ENERGY_CSV, ENERGY_ITEMS)):
            try:
                raw = await _download(client, url)
            except httpx.HTTPError as exc:
                result.errors.append(f"{label}: {exc!r}")
                log.warning("market prices: %s download failed: %r", label, exc)
                continue
            with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as fh:
                batch: list[dict] = []
                for rec in parse_rtp(fh, items):
                    batch.append(rec)
                    result.series.add((rec["market"], rec["item"], rec["source"]))
                    if len(batch) >= 1000:
                        await session.execute(UPSERT, batch)
                        result.rows += len(batch)
                        batch = []
                if batch:
                    await session.execute(UPSERT, batch)
                    result.rows += len(batch)
        if not result.rows and not result.errors:
            result.errors.append("no rows parsed — file layout may have changed")
        await _record_run(session, written=result.rows, started_at=started,
                          error="; ".join(result.errors) if result.errors else None)
        await session.commit()
    log.info("market prices: %d rows across %d series%s", result.rows, len(result.series),
             f" — {len(result.errors)} error(s)" if result.errors else "")
    return result


async def run_market_price_ingest() -> None:
    """Scheduler entry point."""
    await ingest()
