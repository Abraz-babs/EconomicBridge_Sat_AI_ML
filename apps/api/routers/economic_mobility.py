"""Module 06 (Mobility Compass).

GET /api/v1/economic_mobility/compass — every LGA against five measured
factors (2026-09-28): activity, this season's farming, the walk to care,
health facilities per person, and food and fuel prices; signals are a count,
never a score. GET /api/v1/economic_mobility/light-trend — where activity is
growing or fading: NASA Black Marble yearly night light since 2012 by LGA and
village. GET /api/v1/economic_mobility/indicators — the earlier per-LGA
estimates below (withdrawn from the page 2026-09-26; the page reads only
their state-level income median, via /compass).

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
from routers.cropguard import LAND_CHANGE_MODEL, _season_lgas
from routers.skills import GRID3_STATE
from schemas.economic_mobility import (
    CompassData,
    CompassLga,
    CompassPrice,
    CompassPricePoint,
    FarVillage,
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


# ─── The compass: five measured factors per LGA ──────────────────────────
#
# Approved 2026-09-28 (mock v7). Each factor is measured on its own and shown
# on its own; the only roll-up is a COUNT of readings that point to pressure.
# There is deliberately no score: a score would blend a satellite measurement,
# a model of travel time and a price into one number nobody could check.

SIGNAL_FADING = "activity fading"
SIGNAL_FARM_BEHIND = "farming behind"
SIGNAL_FARM_FLAT = "farming flat"
SIGNAL_FAR = "far from care"
FARMING_FLAT_PCT = 5.0        # less than 5% greener than last season, same ground
FAR_SHARE = 0.5               # half or more of the people…
FAR_WALK_MIN = 60.0           # …more than an hour's walk from a health facility
FAR_VILLAGE_MIN_PEOPLE = 300  # the far-from-care list skips hamlets
FAR_LIST = 40
ACCESS_SOURCE = "d4c_travel_2024_v1"
RTP_ESTIMATE = "wb_rtp_estimate_v1"
RTP_SURVEY = "wb_rtp_survey_v1"
FOOD_MONTHS = 36
PETROL_MONTHS = 12            # before 2024 the petrol estimates run far below pump prices
SURVEY_FRESH_DAYS = 366
PUBLISH_FRESH_DAYS = 183
FOOD_TILES = 5
FOOD_ORDER = ("maize", "sorghum", "rice", "gari", "millet", "cowpea")

# World Bank market inside each state (adm1, market) and the zone average the
# rest fall back to. Measured 2026-09-28 — see tasks/market_prices_ingest.py.
WB_MARKET = {"zamfara": ("Zamfara", "Kaura Namoda"), "kaduna": ("Kaduna", "Giwa"),
             "kebbi": ("Kebbi", "Gwandu")}
WB_ZONE = {"kebbi": "North West", "zamfara": "North West", "kaduna": "North West",
           "niger": "North Central", "benue": "North Central", "plateau": "North Central",
           "nasarawa": "North Central", "fct": "North Central"}
WB_ALL = ("Market Average", "Market Average")
STATE_LABEL = {"kebbi": "Kebbi", "zamfara": "Zamfara", "kaduna": "Kaduna", "niger": "Niger",
               "benue": "Benue", "plateau": "Plateau", "nasarawa": "Nasarawa", "fct": "FCT"}


def _signals(light_category: str | None, season_pct: float | None,
             over_hour_share: float | None) -> list[str]:
    """The readings that point to pressure on livelihoods and services. A count, not a score."""
    out: list[str] = []
    if light_category == "dimmer":
        out.append(SIGNAL_FADING)
    if season_pct is not None and season_pct < FARMING_FLAT_PCT:
        out.append(SIGNAL_FARM_BEHIND if season_pct < 0 else SIGNAL_FARM_FLAT)
    if over_hour_share is not None and over_hour_share >= FAR_SHARE:
        out.append(SIGNAL_FAR)
    return out


def _wquantile(values: Sequence[float], weights: Sequence[float], q: float) -> float | None:
    """People-weighted quantile; None when nobody is weighed."""
    pairs = sorted((v, w) for v, w in zip(values, weights) if w > 0)
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


def _access_by_lga(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per LGA: people, weighted median walk / drive minutes, people over an hour's walk.

    The share is over the people whose village HAS a travel time, so a gap in
    the surface never reads as "close to care".
    """
    by: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["lga"] or "Unknown", []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for lga, rs in by.items():
        people = sum(int(r["people"] or 0) for r in rs)
        walk = [(float(r["walk_min"]), int(r["people"] or 0)) for r in rs if r["walk_min"] is not None]
        drive = [(float(r["drive_min"]), int(r["people"] or 0)) for r in rs if r["drive_min"] is not None]
        timed = sum(w for _, w in walk)
        over = sum(w for v, w in walk if v > FAR_WALK_MIN)
        wm = _wquantile([v for v, _ in walk], [w for _, w in walk], 0.5)
        dm = _wquantile([v for v, _ in drive], [w for _, w in drive], 0.5)
        out[lga] = {
            "people": people, "over_hour_walk_people": over,
            "over_hour_walk_share": round(over / timed, 3) if timed else None,
            "walk_median_min": round(wm, 0) if wm is not None else None,
            "drive_median_min": round(dm, 0) if dm is not None else None,
        }
    return out


def _fresh(d: date | None, today: date, days: int) -> bool:
    return d is not None and (today - d).days <= days


def _month_floor(today: date, months: int) -> date:
    y, m = today.year, today.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def _pick_prices(tenant: str, wb: Sequence[Mapping[str, Any]], surveyed: Mapping[tuple[str, str, str], date],
                 published: Sequence[Mapping[str, Any]], today: date) -> list[CompassPrice]:
    """Choose, per item, the best-evidenced series. Pure, for testing.

    Food, in order: a World Bank market in the state surveyed in the last
    year; FEWS NET / NBS published in the last six months; the World Bank
    zone average surveyed in the last year; then whatever exists, published
    prices before model estimates. Petrol: the state's market, else the
    all-market average — always a model estimate, last 12 months only.
    """
    est: dict[tuple[str, str, str], list[tuple[date, float]]] = {}
    for r in wb:
        est.setdefault((r["adm1"], r["market"], r["item"]), []).append((r["observed_at"], float(r["price_ngn"])))
    for s in est.values():
        s.sort()
    pub: dict[str, tuple[str, list[tuple[date, float]]]] = {}
    for r in published:
        _src, pts = pub.setdefault(r["crop"], (r["source"], []))
        pts.append((r["month"], float(r["price_ngn_per_kg"])))
    for _src, pts in pub.values():
        pts.sort()

    food_since = _month_floor(today, FOOD_MONTHS)
    zone = WB_ZONE.get(tenant)
    market = WB_MARKET.get(tenant)
    state = STATE_LABEL.get(tenant, tenant.title())

    def wb_tile(item: str, adm1: str, mkt: str, place: str, since: date) -> CompassPrice | None:
        pts = [(d, p) for d, p in est.get((adm1, mkt, item), []) if d >= since]
        if not pts:
            return None
        return CompassPrice(
            item=item, unit="litre" if item == "petrol" else "kg", publisher="World Bank",
            place=place, modelled=True, last_surveyed=surveyed.get((adm1, mkt, item)),
            stale=not _fresh(pts[-1][0], today, PUBLISH_FRESH_DAYS),
            points=[CompassPricePoint(month=d, price_ngn=round(p, 2)) for d, p in pts])

    def pub_tile(item: str) -> CompassPrice | None:
        if item not in pub:
            return None
        src, allpts = pub[item]
        pts = [(d, p) for d, p in allpts if d >= food_since]
        if not pts:
            return None
        fews = src.startswith("fews")
        return CompassPrice(
            item=item, unit="kg", publisher="FEWS NET" if fews else "NBS",
            place=f"{state} markets" if fews else f"{zone or state} average",
            stale=not _fresh(pts[-1][0], today, PUBLISH_FRESH_DAYS),
            points=[CompassPricePoint(month=d, price_ngn=round(p, 2)) for d, p in pts])

    tiles: list[tuple[bool, int, CompassPrice]] = []
    for rank, item in enumerate(FOOD_ORDER):
        m_tile = wb_tile(item, market[0], market[1], f"{market[1]} market", food_since) if market else None
        z_tile = wb_tile(item, "Geopolitical Zone", zone, f"{zone} average", food_since) if zone else None
        p_tile = pub_tile(item)
        ranked = [
            m_tile if m_tile and _fresh(m_tile.last_surveyed, today, SURVEY_FRESH_DAYS) else None,
            p_tile if p_tile and not p_tile.stale else None,
            z_tile if z_tile and _fresh(z_tile.last_surveyed, today, SURVEY_FRESH_DAYS) else None,
            p_tile, m_tile, z_tile,
        ]
        pick = next((t for t in ranked if t is not None), None)
        if pick is None:
            continue
        current = ((pick.modelled and _fresh(pick.last_surveyed, today, SURVEY_FRESH_DAYS))
                   or (not pick.modelled and not pick.stale))
        tiles.append((not current, rank, pick))
    tiles.sort(key=lambda t: (t[0], t[1]))
    foods = [t for _, _, t in tiles[:FOOD_TILES]]

    petrol_since = _month_floor(today, PETROL_MONTHS + 1)
    petrol = None
    if market:
        petrol = wb_tile("petrol", market[0], market[1], f"{market[1]} market", petrol_since)
    if petrol is None and zone:
        petrol = wb_tile("petrol", WB_ALL[0], WB_ALL[1], "average of the World Bank's markets", petrol_since)
    if petrol is not None:
        petrol.points = petrol.points[-(PETROL_MONTHS + 1):]
    return ([petrol] if petrol else []) + foods


def _round_to(v: float | None, step: int) -> int | None:
    return int(round(float(v) / step) * step) if v is not None else None


@router.get(
    "/compass",
    response_model=SuccessResponse[CompassData],
    summary="Every LGA against five measured factors: activity, farming, care, facilities, prices",
)
async def compass(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[CompassData]:
    """The Mobility Compass.

    Activity: NASA Black Marble light (lga_night_light, as /light-trend).
    Farming: Sentinel-2 farmland greenness this season vs last, same ground
    (lga_season_vegetation, as /cropguard/season). Care: modelled travel time
    from every village to the nearest health facility (village_access, Data
    for Children Collaborative) and GRID3 facilities per 10,000 people.
    Prices: World Bank real-time prices and FEWS NET / NBS. Storms and
    extreme-rain advisory days this rainy season come from ShockGuard.
    """
    tenant_id = _require_tenant(request)
    meta = ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                        timestamp=datetime.now(timezone.utc), pagination=None)
    today = date.today()

    async def exists(*tables: str) -> bool:
        cond = " AND ".join(f"to_regclass('{t}') IS NOT NULL" for t in tables)
        return bool((await session.execute(text(f"SELECT {cond}"))).scalar())

    # State household income — a state-level estimate (World Bank income scaled
    # to the NBS living-standards survey), never per LGA.
    income_usd = income_ngn = None
    if await exists("mobility_indicators"):
        inc = (await session.execute(text(
            """
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_household_income_usd) AS usd,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_household_income_ngn) AS ngn
              FROM (SELECT DISTINCT ON (lga) avg_household_income_usd, avg_household_income_ngn
                      FROM mobility_indicators WHERE source <> 'seed_v1'
                     ORDER BY lga, observed_at DESC) latest
            """
        ))).mappings().one()
        income_usd = _round_to(inc["usd"], 5)
        income_ngn = _round_to(inc["ngn"], 1000)

    if tenant_id not in NIGERIAN_PILOTS:
        return SuccessResponse(data=CompassData(
            reason="The compass covers the Nigerian pilots first; this pilot follows.",
            income_usd_month=income_usd, income_ngn_month=income_ngn), meta=meta)

    # Activity
    light: dict[str, LightTrendLga] = {}
    if await exists("lga_night_light"):
        lrows = (await session.execute(text(
            "SELECT lga, year, composite, radiance_sum, lit_km2 FROM lga_night_light ORDER BY lga, year"
        ))).mappings().all()
        light = {g.lga: g for g in _build_light_lgas(list(lrows), {})[0]}

    # Farming this season
    season: dict[str, float | None] = {}
    season_year = prev_year = None
    season_state = None
    if await exists("lga_season_vegetation"):
        veg = (await session.execute(text(
            """
            SELECT lga, season_year, lga_ha, greened_on_crops_ha, greened_on_rangeland_ha,
                   greened_ha_common, prev_greened_ha_common, common_observed_ha, window_end
              FROM lga_season_vegetation WHERE detector_version = :dv
            """
        ), {"dv": LAND_CHANGE_MODEL})).mappings().all()
        srows, season_year, prev_year = _season_lgas(list(veg), {})
        season = {r.lga: r.like_for_like_pct for r in srows}
        latest = [v for v in veg if season_year is not None and int(v["season_year"]) == season_year]
        common = sum(float(v["greened_ha_common"] or 0) for v in latest)
        prev_common = sum(float(v["prev_greened_ha_common"] or 0) for v in latest)
        season_state = round(100.0 * (common / prev_common - 1.0), 1) if prev_common else None

    # Care: travel time at every village
    access: dict[str, dict[str, Any]] = {}
    far: list[FarVillage] = []
    state_people = state_over = 0
    state_median: float | None = None
    if await exists("village_access"):
        arows = (await session.execute(text(
            "SELECT lga, people, walk_min, drive_min FROM village_access WHERE source = :s"
        ), {"s": ACCESS_SOURCE})).mappings().all()
        access = _access_by_lga(list(arows))
        walk = [(float(r["walk_min"]), int(r["people"] or 0)) for r in arows if r["walk_min"] is not None]
        state_people = sum(int(r["people"] or 0) for r in arows)
        state_over = sum(w for v, w in walk if v > FAR_WALK_MIN)
        state_median = _wquantile([v for v, _ in walk], [w for _, w in walk], 0.5)
        far = [FarVillage(
            name=r["name"], ward=r["ward"], lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])), people=int(r["people"] or 0),
            walk_min=round(float(r["walk_min"]), 0),
            drive_min=round(float(r["drive_min"]), 0) if r["drive_min"] is not None else None,
        ) for r in (await session.execute(text(
            """
            SELECT name, ward, lga, ST_X(geom) AS lon, ST_Y(geom) AS lat, people, walk_min, drive_min
              FROM village_access
             WHERE source = :s AND walk_min IS NOT NULL AND people >= :minp
             ORDER BY walk_min DESC, people DESC
             LIMIT :n
            """
        ), {"s": ACCESS_SOURCE, "minp": FAR_VILLAGE_MIN_PEOPLE, "n": FAR_LIST})).mappings().all()]

    # Health facilities: one GRID3 release per state; each located facility
    # belongs to the LGA of its nearest village.
    facilities: dict[str, int] = {}
    release = None
    fac_total = fac_unlocated = None
    grid3_state = GRID3_STATE.get(tenant_id)
    if grid3_state and await exists("public.health_facilities", "village_light"):
        rel = (await session.execute(text(
            """
            SELECT release, count(*) AS n, count(*) FILTER (WHERE geom IS NULL) AS unlocated
              FROM public.health_facilities WHERE state = :st GROUP BY release
            """
        ), {"st": grid3_state})).mappings().all()
        by_rel = {r["release"]: r for r in rel}
        release = "v3.0" if "v3.0" in by_rel else ("v2.0" if "v2.0" in by_rel else None)
        if release:
            fac_total = int(by_rel[release]["n"])
            fac_unlocated = int(by_rel[release]["unlocated"])
            facilities = {r["lga"]: int(r["n"]) for r in (await session.execute(text(
                """
                SELECT v.lga, count(*) AS n
                  FROM public.health_facilities f
                  CROSS JOIN LATERAL (
                      SELECT lga FROM village_light
                       WHERE period = (SELECT max(period) FROM village_light)
                       ORDER BY geom <-> f.geom LIMIT 1) v
                 WHERE f.state = :st AND f.release = :rel AND f.geom IS NOT NULL
                 GROUP BY v.lga
                """
            ), {"st": grid3_state, "rel": release})).mappings().all() if r["lga"]}

    # This rainy season, from ShockGuard
    since = date(today.year if today.month >= 5 else today.year - 1, 5, 1)
    storms: dict[str, int] = {}
    advisories: dict[str, int] = {}
    if await exists("storm_events"):
        storms = {r["lga"]: int(r["n"]) for r in (await session.execute(text(
            "SELECT lga, count(*) AS n FROM storm_events WHERE peak_at >= :d GROUP BY lga"
        ), {"d": datetime(since.year, since.month, since.day, tzinfo=timezone.utc)})).mappings().all()}
    if await exists("rainfall_advisory_history"):
        advisories = {r["lga"]: int(r["n"]) for r in (await session.execute(text(
            "SELECT lga, count(DISTINCT observed_date) AS n FROM rainfall_advisory_history "
            "WHERE observed_date >= :d GROUP BY lga"
        ), {"d": since})).mappings().all()}

    # Prices
    adm1s = ["Geopolitical Zone", WB_ALL[0]] + ([WB_MARKET[tenant_id][0]] if tenant_id in WB_MARKET else [])
    wb_rows: list[Mapping[str, Any]] = []
    surveyed: dict[tuple[str, str, str], date] = {}
    if await exists("public.market_prices"):
        wb_rows = list((await session.execute(text(
            """
            SELECT item, adm1, market, observed_at, price_ngn FROM public.market_prices
             WHERE source = :est AND adm1 = ANY(:adm1) AND observed_at >= :since
            """
        ), {"est": RTP_ESTIMATE, "adm1": adm1s, "since": _month_floor(today, FOOD_MONTHS)})).mappings().all())
        surveyed = {(r["adm1"], r["market"], r["item"]): r["last"] for r in (await session.execute(text(
            """
            SELECT adm1, market, item, max(observed_at) AS last FROM public.market_prices
             WHERE source = :sv AND adm1 = ANY(:adm1) GROUP BY 1, 2, 3
            """
        ), {"sv": RTP_SURVEY, "adm1": adm1s})).mappings().all()}
    published = (await session.execute(text(
        """
        SELECT crop, observed_at AS month, price_ngn_per_kg, source
          FROM public.crop_prices
         WHERE region = :region AND crop = ANY(:crops) AND source <> 'seed_v1'
           AND observed_at >= :since
        """
    ), {"region": tenant_id, "crops": list(FOOD_ORDER),
        "since": _month_floor(today, FOOD_MONTHS)})).mappings().all()
    prices = _pick_prices(tenant_id, wb_rows, surveyed, list(published), today)

    names = sorted(set(light) | set(season) | {k for k in access if k != "Unknown"})
    lgas: list[CompassLga] = []
    for name in names:
        g = light.get(name)
        a = access.get(name, {})
        n_fac = facilities.get(name, 0)
        people = int(a.get("people") or 0)
        try:
            c = lga_geo.centroid_for(tenant_id, name)
            loc: LonLat | None = LonLat(lon=c[0], lat=c[1])
        except KeyError:
            loc = None
        share = a.get("over_hour_walk_share")
        lgas.append(CompassLga(
            lga=name, location=loc, people=people,
            light_category=g.category if g else None,
            light_change_pct=g.change_pct if g else None,
            season_pct=season.get(name),
            walk_median_min=a.get("walk_median_min"), drive_median_min=a.get("drive_median_min"),
            over_hour_walk_people=int(a.get("over_hour_walk_people") or 0),
            over_hour_walk_share=share,
            facilities=n_fac if release else None,
            facilities_per_10k=round(10000 * n_fac / people, 1) if release and people else None,
            storms=storms.get(name, 0), advisories=advisories.get(name, 0),
            signals=_signals(g.category if g else None, season.get(name), share),
        ))
    lgas.sort(key=lambda r: (-len(r.signals),
                             r.light_change_pct if r.light_change_pct is not None else float("inf"),
                             r.lga))

    return SuccessResponse(data=CompassData(
        available=bool(lgas),
        reason=None if lgas else "The compass has not been measured for this state yet.",
        season_year=season_year, previous_year=prev_year, season_state_pct=season_state,
        season_since=since, people=state_people, over_hour_walk_people=state_over,
        walk_median_min=round(state_median, 0) if state_median is not None else None,
        access_measured=bool(access), facilities_release=release,
        facilities_total=fac_total, facilities_unlocated=fac_unlocated,
        lgas=lgas, far_from_care=far, prices=prices,
        income_usd_month=income_usd, income_ngn_month=income_ngn,
    ), meta=meta)
