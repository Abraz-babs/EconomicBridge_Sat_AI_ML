"""Module 06 (Mobility Compass).

GET /api/v1/economic_mobility/light-trend — where activity is growing or
fading (2026-09-27): NASA Black Marble yearly night light since 2012 by LGA
and village, with staple food prices. GET /api/v1/economic_mobility/indicators
— the earlier per-LGA estimates below (withdrawn from the page 2026-09-26).

Read-only consumer of `tenant_<id>.mobility_indicators` (migration 0022).
Returns the full per-LGA list plus aggregate rollups (median COL,
median income, cheapest/most-expensive LGA, best opportunity / capacity)
so the dashboard renders without doing the math client-side.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.economic_mobility import (
    LightTrendData,
    LightTrendLga,
    StaplePrice,
    StapleSeries,
    TrendVillage,
    LonLat,
    MobilityIndicatorRow,
    MobilityStatsData,
)
from schemas.envelope import ResponseMeta, SuccessResponse
from services import lga_geo


router = APIRouter(prefix="/economic_mobility", tags=["economic-mobility"])


def _trace_id(request: Request) -> UUID:
    return getattr(request.state, "trace_id", uuid4())


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required for this endpoint",
        )
    return tenant_id


def _median_int(values: list[int | None]) -> int | None:
    """Median of the non-null values, or None when none are present.

    NGN is absent for ECOWAS (USD-only) tenants, so each currency's median
    is computed over whichever rows actually carry it."""
    present = sorted(v for v in values if v is not None)
    if not present:
        return None
    return present[len(present) // 2]


def _col_band(col: float) -> str:
    """Map cost-of-living index to a descriptive band the dashboard uses
    to colour the LGA points (cheaper → green, expensive → red)."""
    if col >= 140:
        return "premium"
    if col >= 110:
        return "above_avg"
    if col >= 85:
        return "near_avg"
    return "below_avg"


@router.get(
    "/indicators",
    response_model=SuccessResponse[MobilityStatsData],
    summary="Per-LGA mobility indicators + aggregate stats for a tenant",
)
async def list_indicators(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=2000, description="Max LGAs returned.")
    ] = 1000,
) -> SuccessResponse[MobilityStatsData]:
    tenant_id = _require_tenant(request)

    # Source-preference dedup (Slice 21): a tenant can hold both seed_v1
    # and live (nbs_col_v1 / ecowas_stat_v1) rows for the same LGA — the
    # swap-in coexistence the table's UNIQUE(tenant,lga,source) allows.
    # DISTINCT ON (lga) keeps ONE row per LGA, preferring a live source
    # over seed (priority 0 vs 9), newest observed_at as tiebreak — so
    # the dashboard shows each LGA once and automatically upgrades to
    # live data the moment an ingest lands.
    result = await session.execute(
        text(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (lga)
                       id, tenant_id, lga,
                       ST_X(location) AS lon, ST_Y(location) AS lat,
                       cost_of_living_index, avg_household_income_ngn,
                       avg_household_income_usd,
                       income_opportunity_score, displacement_capacity_index,
                       population, observed_at, source, created_at, updated_at
                  FROM mobility_indicators
                 ORDER BY lga,
                          CASE
                            WHEN source = 'seed_v1' THEN 9
                            ELSE 0
                          END,
                          observed_at DESC
            ) deduped
             ORDER BY cost_of_living_index DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    indicators = [
        MobilityIndicatorRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            cost_of_living_index=float(r["cost_of_living_index"]),
            cost_of_living_band=_col_band(float(r["cost_of_living_index"])),
            avg_household_income_ngn=(
                int(r["avg_household_income_ngn"])
                if r["avg_household_income_ngn"] is not None else None
            ),
            avg_household_income_usd=(
                int(r["avg_household_income_usd"])
                if r["avg_household_income_usd"] is not None else None
            ),
            income_opportunity_score=float(r["income_opportunity_score"]),
            displacement_capacity_index=float(r["displacement_capacity_index"]),
            population=int(r["population"]),
            observed_at=r["observed_at"],
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    if indicators:
        sorted_col = sorted(indicators, key=lambda i: i.cost_of_living_index)
        cheapest = sorted_col[0].lga
        most_expensive = sorted_col[-1].lga
        median_col = sorted_col[len(sorted_col) // 2].cost_of_living_index
        # Median over whichever currency is present (NGN absent for ECOWAS).
        median_income_ngn = _median_int(
            [i.avg_household_income_ngn for i in indicators]
        )
        median_income_usd = _median_int(
            [i.avg_household_income_usd for i in indicators]
        )
        best_opp = max(indicators, key=lambda i: i.income_opportunity_score).lga
        best_cap = max(indicators, key=lambda i: i.displacement_capacity_index).lga
    else:
        cheapest = most_expensive = best_opp = best_cap = None
        median_col = 0.0
        median_income_ngn = median_income_usd = None

    sources = sorted({i.source for i in indicators})

    return SuccessResponse(
        data=MobilityStatsData(
            tenant_id=tenant_id,
            total_lgas=len(indicators),
            median_cost_of_living=median_col,
            median_household_income_ngn=median_income_ngn,
            median_household_income_usd=median_income_usd,
            cheapest_lga=cheapest,
            most_expensive_lga=most_expensive,
            best_opportunity_lga=best_opp,
            best_capacity_lga=best_cap,
            indicators=indicators,
            sources=sources,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


# ─── Night-light trend ────────────────────────────────────────────────────

LIGHT_WINDOW = 3          # years averaged at each end of the series
TINY_LIGHT = 2.0          # summed radiance below this is a few faint pixels: no % is meaningful
STEADY_PCT = 10.0         # changes smaller than this on both composites are "steady"
VILLAGE_LIST = 40
STAPLES = ("maize", "sorghum", "millet", "rice", "cowpea")
PRICE_MONTHS = 36
NIGERIAN_PILOTS = {"kebbi", "zamfara", "niger", "kaduna", "benue", "plateau", "nasarawa", "fct"}


def _ends(series: Sequence[float | None], window: int = LIGHT_WINDOW) -> tuple[float | None, float | None]:
    """Average of the first and of the last `window` years that have a reading."""
    def avg(xs: Sequence[float | None]) -> float | None:
        v = [x for x in xs if x is not None]
        return sum(v) / len(v) if v else None
    return avg(series[:window]), avg(series[-window:])


def _shape(series: Sequence[float | None]) -> tuple[str | None, float | None]:
    """('pct', change) for a real base; 'new' / 'dark' when the start was only faint light."""
    a, b = _ends(series)
    if a is None or b is None:
        return None, None
    if a >= TINY_LIGHT:
        return "pct", (b / a - 1) * 100
    return ("new" if b >= TINY_LIGHT else "dark"), None


def _classify_lga(near: Sequence[float | None], allang: Sequence[float | None]
                  ) -> tuple[str, float | None]:
    """(category, near-nadir change %) — a change counts only when both composites agree.

    Pure, so the rule is testable without a database. Categories: dimmer,
    brighter, new_light (little light at the start, lit now), steady,
    still_dark (little light either time), mixed (the composites disagree or
    a series is missing).
    """
    sn, pn = _shape(near)
    sa, pa = _shape(allang)
    if sn is None or sa is None:
        return "mixed", pn
    if sn != "pct" or sa != "pct":
        brighter_both = {sn, sa} <= {"pct", "new"} and ((pn if sn == "pct" else pa) or 0) >= STEADY_PCT
        if sn != sa and not brighter_both:
            return "mixed", pn
        if sn == "new" or sa == "new":
            return ("new_light" if sn == "new" else "brighter"), pn
        return "still_dark", None
    assert pn is not None and pa is not None
    if abs(pn) < STEADY_PCT and abs(pa) < STEADY_PCT:
        return "steady", pn
    if (pn > 0) != (pa > 0):
        return "mixed", pn
    if pn <= -STEADY_PCT:
        return "dimmer", pn
    if pn >= STEADY_PCT:
        return "brighter", pn
    return "steady", pn


def _build_light_lgas(
    rows: list[Mapping[str, Any]],
    villages: dict[str, Mapping[str, Any]],
    centroid: Any = None,
) -> tuple[list[LightTrendLga], int, int]:
    """Per-LGA series and category from lga_night_light rows. Returns (lgas, first, last)."""
    years = sorted({int(r["year"]) for r in rows})
    if not years:
        return [], 0, 0
    idx = {y: i for i, y in enumerate(years)}
    series: dict[str, dict[str, list[float | None]]] = {}
    lit: dict[str, list[float | None]] = {}
    for r in rows:
        lga = r["lga"]
        per = series.setdefault(lga, {"near_nadir": [None] * len(years), "all_angle": [None] * len(years)})
        if r["composite"] in per:
            per[r["composite"]][idx[int(r["year"])]] = round(float(r["radiance_sum"]), 1)
        if r["composite"] == "near_nadir":
            lit.setdefault(lga, [None] * len(years))[idx[int(r["year"])]] = float(r["lit_km2"])
    out: list[LightTrendLga] = []
    for lga, per in series.items():
        cat, pct = _classify_lga(per["near_nadir"], per["all_angle"])
        l0, l1 = _ends(lit.get(lga, []))
        v = villages.get(lga) or {}
        loc = centroid(lga) if centroid else None
        out.append(LightTrendLga(
            lga=lga, location=LonLat(lon=loc[0], lat=loc[1]) if loc else None, years=years,
            near_nadir=per["near_nadir"], all_angle=per["all_angle"],
            change_pct=round(pct, 1) if pct is not None else None, category=cat,
            lit_km2_start=round(l0, 1) if l0 is not None else None,
            lit_km2_now=round(l1, 1) if l1 is not None else None,
            people=int(v.get("people") or 0), villages=int(v.get("villages") or 0),
            gone_dark=int(v.get("gone_dark") or 0), newly_lit=int(v.get("newly_lit") or 0),
        ))
    order = {"dimmer": 0, "mixed": 1, "steady": 2, "still_dark": 3, "brighter": 4, "new_light": 5}
    out.sort(key=lambda g: (order[g.category], g.change_pct if g.change_pct is not None else 0.0, g.lga))
    return out, years[0], years[-1]


def _village(r: Mapping[str, Any]) -> TrendVillage:
    return TrendVillage(
        name=r["name"], ward=r.get("ward"), lga=r.get("lga"),
        location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])), people=int(r.get("people") or 0),
        since_year=r.get("since_year"),
        near_nadir=[None if x is None else round(float(x), 2) for x in (r.get("near_nadir") or [])],
    )


@router.get(
    "/light-trend",
    response_model=SuccessResponse[LightTrendData],
    summary="Light at night by LGA and village since 2012, with staple food prices",
)
async def light_trend(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[LightTrendData]:
    """Where activity is growing or fading.

    NASA Black Marble yearly composites (VNP46A4) summed over each LGA and read
    at each GRID3 village, 2012 to the latest year; a change is shown only when
    both of NASA's composites agree. Staple prices from public.crop_prices
    (FEWS NET market / NBS zone), never the seed series. Light is activity, not
    income, and the page says so.
    """
    tenant_id = _require_tenant(request)
    meta = ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                        timestamp=datetime.now(timezone.utc), pagination=None)

    prices: list[StapleSeries] = []
    today = date.today()
    since = date(today.year - PRICE_MONTHS // 12, today.month, 1)   # observed_at is DATE
    price_rows = (await session.execute(text(
        """
        SELECT crop, observed_at AS month, price_ngn_per_kg, source
          FROM public.crop_prices
         WHERE region = :region AND crop = ANY(:crops) AND source <> 'seed_v1'
           AND observed_at >= :since
         ORDER BY crop, observed_at
        """
    ), {"region": tenant_id, "crops": list(STAPLES), "since": since})).mappings().all()
    by_crop: dict[str, StapleSeries] = {}
    for r in price_rows:
        ser = by_crop.setdefault(r["crop"], StapleSeries(crop=r["crop"], source=r["source"]))
        ser.points.append(StaplePrice(month=r["month"], price_ngn_per_kg=float(r["price_ngn_per_kg"])))
    prices = [by_crop[c] for c in STAPLES if c in by_crop]

    ready = (await session.execute(text(
        "SELECT to_regclass('lga_night_light') IS NOT NULL AND to_regclass('village_light_trend') IS NOT NULL"
    ))).scalar()
    rows = []
    if ready:
        rows = (await session.execute(text(
            "SELECT lga, year, composite, radiance_sum, lit_km2 FROM lga_night_light ORDER BY lga, year"
        ))).mappings().all()
    if not rows:
        reason = ("Night-light trends cover the Nigerian pilots first; this pilot follows."
                  if tenant_id not in NIGERIAN_PILOTS
                  else "Night light has not been measured for this state yet.")
        return SuccessResponse(data=LightTrendData(reason=reason, prices=prices), meta=meta)

    last_v = (await session.execute(text("SELECT max(last_year) FROM village_light_trend"))).scalar()
    villages: dict[str, Mapping[str, Any]] = {}
    gone: list[TrendVillage] = []
    new: list[TrendVillage] = []
    totals = {"gone_dark": 0, "gone_dark_people": 0, "newly_lit": 0, "newly_lit_people": 0}
    if last_v is not None:
        villages = {r["lga"]: r for r in (await session.execute(text(
            """
            SELECT lga, count(*) AS villages, sum(people) AS people,
                   count(*) FILTER (WHERE status = 'gone_dark') AS gone_dark,
                   count(*) FILTER (WHERE status = 'newly_lit') AS newly_lit
              FROM village_light_trend WHERE last_year = :y GROUP BY lga
            """
        ), {"y": last_v})).mappings().all()}
        for status, bucket in (("gone_dark", gone), ("newly_lit", new)):
            t = (await session.execute(text(
                "SELECT count(*) AS n, coalesce(sum(people), 0) AS p FROM village_light_trend "
                "WHERE last_year = :y AND status = :s"), {"y": last_v, "s": status})).mappings().one()
            totals[status] = int(t["n"])
            totals[f"{status}_people"] = int(t["p"])
            bucket.extend(_village(r) for r in (await session.execute(text(
                """
                SELECT name, ward, lga, ST_X(geom) AS lon, ST_Y(geom) AS lat, people,
                       since_year, near_nadir
                  FROM village_light_trend
                 WHERE last_year = :y AND status = :s
                 ORDER BY people DESC, name
                 LIMIT :n
                """
            ), {"y": last_v, "s": status, "n": VILLAGE_LIST})).mappings().all())

    def centroid(lga: str) -> tuple[float, float] | None:
        try:
            return lga_geo.centroid_for(tenant_id, lga)
        except KeyError:
            return None

    lgas, first, last = _build_light_lgas(list(rows), villages, centroid)
    count = {c: sum(1 for g in lgas if g.category == c) for c in
             ("dimmer", "brighter", "new_light", "steady", "still_dark", "mixed")}
    return SuccessResponse(data=LightTrendData(
        available=True, first_year=first, last_year=last, window=LIGHT_WINDOW, lgas=lgas,
        dimmer=count["dimmer"], brighter=count["brighter"] + count["new_light"],
        steady=count["steady"], still_dark=count["still_dark"], mixed=count["mixed"],
        people_in_dimmer=sum(g.people for g in lgas if g.category == "dimmer"),
        villages_gone_dark=gone, villages_newly_lit=new, prices=prices, **totals,
    ), meta=meta)
