"""Monthly food-price ingest — NBS zone prices + FEWS NET market overlay.

Writes `public.crop_prices` (crop, region, observed_at, price_ngn_per_kg,
source). Runs monthly because both upstreams publish monthly.

WHY TWO SOURCES, AND WHY THEY ARE NOT MERGED INTO ONE NUMBER
------------------------------------------------------------
They answer different questions at different resolutions:

  nbs_zone_v1     every pilot, every month, ~24 crops — but the finest
                  granularity NBS publishes is the geopolitical ZONE, so
                  Kebbi and Zamfara necessarily share a figure.
  fews_market_v1  a real per-state figure aggregated from named markets, but
                  only where FEWS actually collects: Zamfara (current),
                  Kebbi and Kaduna (stop 2025-01), and NOTHING for Niger,
                  Benue, Plateau, Nasarawa or FCT.

Averaging them would invent a number neither publisher stands behind, and
would quietly change meaning depending on which source happened to have data
that month. So BOTH are written as separate rows, distinguished by `source`
and by `region`:

    region "kebbi" + source nbs_zone_v1     -> the NORTH WEST zone average
    region "kebbi" + source fews_market_v1  -> a Kebbi market figure

`region` is the TENANT ID, because routers/cropguard_prices.py resolves the
region from X-Tenant-Id — writing "Zamfara" or "NORTH WEST" there puts rows in
the table that the panel can never query. The honesty therefore lives in
`source`, not in `region`: an nbs_zone_v1 row against kebbi IS the North West
average and must be labelled as such wherever it is shown. A zone average must
never be presented as a state price — the same overstatement as pinning a
statewide flood to one LGA.

IDEMPOTENT: each run deletes the (source, observed_at) slices it is about to
write, so re-running a month corrects it rather than duplicating it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session_factory
from sources.fews_prices import SOURCE_TAG as FEWS_SOURCE
from sources.fews_prices import FewsFetchError, FewsPriceClient
from sources.nbs_food_prices import SOURCE_TAG as NBS_SOURCE
from sources.nbs_food_prices import (
    ZONE_BY_TENANT,
    NbsFetchError,
    NbsFoodPriceClient,
    NbsSchemaError,
)

log = logging.getLogger(__name__)

RUN_SOURCE = "food_prices_v1"       # the ingestion_runs tag for the whole job

# NBS: how many monthly workbooks to (re)fetch. It publishes weeks after the
# month ends, so a short trailing window catches a late release. Each month is
# a separate HTTP request, hence kept small.
LOOKBACK_MONTHS = 3

# FEWS: how far back to keep from the single country dump. Wider on purpose.
# The dump is ONE request regardless of range, so a narrow window costs nothing
# to widen — and a narrow one actively hid data we already had: FEWS stopped
# collecting in Kebbi and Kaduna in Jan 2025, so a 3-month window showed those
# states as empty when a real (if ending) series existed. A chart that visibly
# stops in Jan 2025, dated, is far more useful than no chart, and the panel
# states plainly that an empty chart means nobody is publishing.
FEWS_LOOKBACK_MONTHS = 36


@dataclass
class IngestResult:
    nbs_rows: int = 0
    fews_rows: int = 0
    errors: list[str] = None          # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    @property
    def total(self) -> int:
        return self.nbs_rows + self.fews_rows


def _months_back(n: int, *, today: date | None = None) -> list[date]:
    """First-of-month dates for the trailing `n` months, oldest first."""
    cur = (today or date.today()).replace(day=1)
    out: list[date] = []
    for _ in range(n):
        out.append(cur)
        cur = (cur - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


_INSERT = text(
    """
    INSERT INTO public.crop_prices
        (crop, region, observed_at, price_ngn_per_kg, source)
    VALUES (:crop, :region, :observed_at, :price, :source)
    """
)


async def _replace_slice(
    session: AsyncSession, *, source: str, observed_at: date,
) -> None:
    await session.execute(
        text(
            "DELETE FROM public.crop_prices "
            "WHERE source = :s AND observed_at = :d"
        ),
        {"s": source, "d": observed_at},
    )


async def _record_run(
    session: AsyncSession, *, written: int, started_at, error: str | None,
) -> None:
    """Stamp public.ingestion_runs. Columns are records_ingested /
    error_message / dry_run (migration 0004)."""
    await session.execute(text("""
        INSERT INTO public.ingestion_runs (
            id, source, tenant_id, trigger, started_at, finished_at,
            status, records_ingested, error_message, dry_run
        ) VALUES (
            :id, :source, 'public', :trigger, :started_at, NOW(),
            :status, :written, :error, FALSE
        )
    """), {
        "id": uuid4(), "source": RUN_SOURCE, "trigger": "scheduled",
        "started_at": started_at, "written": written,
        "status": "failed" if error else "succeeded",
        "error": error[:500] if error else None,
    })


async def ingest(today: date | None = None) -> IngestResult:
    """Pull both sources for the trailing window and write them."""
    from datetime import datetime, timezone

    started = datetime.now(timezone.utc)
    result = IngestResult()
    months = _months_back(LOOKBACK_MONTHS, today=today)
    factory = get_session_factory()

    async with factory() as session:
        # ── NBS: one workbook per month, zone granularity, all pilots ──
        nbs = NbsFoodPriceClient()
        for month in months:
            try:
                zone_prices = await nbs.fetch_month(month)
            except NbsSchemaError as exc:
                # Layout drift is worth shouting about — it means the parser is
                # reading a workbook it no longer understands.
                result.errors.append(f"nbs {month:%Y-%m}: {exc}")
                log.error("nbs schema drift for %s: %s", month, exc)
                continue
            except NbsFetchError as exc:
                result.errors.append(f"nbs {month:%Y-%m}: {exc}")
                continue
            if not zone_prices:
                continue
            await _replace_slice(
                session, source=NBS_SOURCE, observed_at=zone_prices[0].observed_at,
            )
            by_zone = {}
            for zp in zone_prices:
                by_zone.setdefault(zp.zone, []).append(zp)
            for tenant, zone in ZONE_BY_TENANT.items():
                for zp in by_zone.get(zone, []):
                    await session.execute(_INSERT, {
                        "crop": zp.crop, "region": tenant,
                        "observed_at": zp.observed_at,
                        "price": zp.price_ngn_per_kg, "source": NBS_SOURCE,
                    })
                    result.nbs_rows += 1

        # ── FEWS: one country dump, filtered to our window and states ──
        try:
            fews_since = _months_back(FEWS_LOOKBACK_MONTHS, today=today)[0]
            fews_rows = await FewsPriceClient().fetch(since=fews_since)
        except FewsFetchError as exc:
            result.errors.append(f"fews: {exc}")
            fews_rows = []
        for observed in {r.observed_at for r in fews_rows}:
            await _replace_slice(
                session, source=FEWS_SOURCE, observed_at=observed,
            )
        for mp in fews_rows:
            await session.execute(_INSERT, {
                "crop": mp.crop, "region": mp.tenant,
                "observed_at": mp.observed_at,
                "price": mp.price_ngn_per_kg, "source": FEWS_SOURCE,
            })
            result.fews_rows += 1

        await _record_run(
            session, written=result.total, started_at=started,
            error="; ".join(result.errors)[:500] if result.errors else None,
        )
        await session.commit()

    log.info(
        "food prices: %d rows (nbs %d zone, fews %d market)%s",
        result.total, result.nbs_rows, result.fews_rows,
        f" — {len(result.errors)} error(s)" if result.errors else "",
    )
    return result


async def run_food_price_ingest() -> None:
    """Scheduler entry point."""
    await ingest()
