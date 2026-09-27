"""Module 07 (SkillsBridge).

GET /api/v1/skills/reach — the school reach list (2026-09-27): every GRID3
school, whether any village within 2 km shows light at night, and the people
living there. GET /api/v1/skills/indicators — the earlier per-LGA view below.

Read-only consumer of `tenant_<id>.skills_indicators` (migration 0023).
Returns the full per-LGA list plus aggregate rollups (median internet
coverage, total schools/youth pop, best-connectivity / worst-gap LGA)
so the dashboard renders without doing the math client-side.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.skills import (
    LonLat,
    ReachLga,
    ReachSchool,
    SchoolReachData,
    SkillsIndicatorRow,
    SkillsStatsData,
)


router = APIRouter(prefix="/skills", tags=["skills"])


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


def _connectivity_band(internet_pct: float) -> str:
    """Map internet coverage % to a descriptive band the dashboard uses
    to colour LGA points (broadband → green, no_signal → red)."""
    if internet_pct >= 60:
        return "broadband"
    if internet_pct >= 30:
        return "basic"
    if internet_pct >= 10:
        return "limited"
    return "no_signal"


@router.get(
    "/indicators",
    response_model=SuccessResponse[SkillsStatsData],
    summary="Per-LGA education + connectivity indicators for a tenant",
)
async def list_indicators(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=2000, description="Max LGAs returned.")
    ] = 1000,
) -> SuccessResponse[SkillsStatsData]:
    tenant_id = _require_tenant(request)

    # Source-preference dedup (Slice 22): a tenant can hold both seed_v1
    # and live (giga_v1) rows per LGA. DISTINCT ON (lga) keeps one row
    # per LGA, preferring any live source over seed (priority 0 vs 9),
    # newest observed_at as tiebreak — so the dashboard shows each LGA
    # once and auto-upgrades to GIGA/ITU data when an ingest lands.
    result = await session.execute(
        text(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (lga)
                       id, tenant_id, lga,
                       ST_X(location) AS lon, ST_Y(location) AS lat,
                       school_count, school_density_per_10k,
                       internet_coverage_pct, mobile_coverage_pct,
                       electricity_reliability, youth_population,
                       learning_gap_index, observed_at, source,
                       created_at, updated_at
                  FROM skills_indicators
                 ORDER BY lga,
                          CASE
                            WHEN source = 'seed_v1' THEN 9
                            ELSE 0
                          END,
                          observed_at DESC
            ) deduped
             ORDER BY learning_gap_index DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    indicators = [
        SkillsIndicatorRow(
            id=r["id"],
            tenant_id=r["tenant_id"],
            lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            school_count=int(r["school_count"]),
            school_density_per_10k=float(r["school_density_per_10k"]),
            internet_coverage_pct=float(r["internet_coverage_pct"]),
            connectivity_band=_connectivity_band(float(r["internet_coverage_pct"])),
            mobile_coverage_pct=float(r["mobile_coverage_pct"]),
            electricity_reliability=float(r["electricity_reliability"]),
            youth_population=int(r["youth_population"]),
            learning_gap_index=float(r["learning_gap_index"]),
            observed_at=r["observed_at"],
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    if indicators:
        sorted_net = sorted(indicators, key=lambda i: i.internet_coverage_pct)
        sorted_density = sorted(indicators, key=lambda i: i.school_density_per_10k)
        median_net = sorted_net[len(sorted_net) // 2].internet_coverage_pct
        median_density = sorted_density[len(sorted_density) // 2].school_density_per_10k
        best_conn = sorted_net[-1].lga
        worst_gap = max(indicators, key=lambda i: i.learning_gap_index).lga
        most_underserved = sorted_density[0].lga
        most_schools = max(indicators, key=lambda i: i.school_count).lga
        total_schools = sum(i.school_count for i in indicators)
        total_youth = sum(i.youth_population for i in indicators)
    else:
        median_net = 0.0
        median_density = 0.0
        best_conn = worst_gap = most_underserved = most_schools = None
        total_schools = 0
        total_youth = 0

    sources = sorted({i.source for i in indicators})

    return SuccessResponse(
        data=SkillsStatsData(
            tenant_id=tenant_id,
            total_lgas=len(indicators),
            median_internet_coverage_pct=median_net,
            median_school_density=median_density,
            total_schools=total_schools,
            total_youth_population=total_youth,
            best_connectivity_lga=best_conn,
            worst_gap_lga=worst_gap,
            most_underserved_lga=most_underserved,
            most_schools_lga=most_schools,
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


# ─── School reach list ────────────────────────────────────────────────────

# Pilot tenant -> GRID3 state name (GRID3 spells the capital territory "Fct").
GRID3_STATE = {
    "kebbi": "Kebbi", "zamfara": "Zamfara", "niger": "Niger", "kaduna": "Kaduna",
    "benue": "Benue", "plateau": "Plateau", "nasarawa": "Nasarawa", "fct": "Fct",
}
REACH_RADIUS_KM = 2.0
# A degree box that always contains the 2 km circle at our latitudes (4-14°N),
# so the GiST index narrows the search before the distance test.
REACH_BOX_DEG = 0.02
# Distance in km on the WGS84 ellipsoid's local scale at the school's latitude
# (km per degree of latitude and of longitude). Measured 2026-09-27 on all
# 5,380 Kaduna schools against geography distance: the same nearest village
# for every school, the same 2 km ring for all but two (one village at the
# edge), and 1.3 s instead of 4.5 s.
_KM = """
    sqrt(power((ST_Y(v.geom) - ST_Y(s.geom)) * (111.132954
            - 0.559822 * cos(radians(2 * ST_Y(s.geom)))
            + 0.001175 * cos(radians(4 * ST_Y(s.geom)))), 2)
       + power((ST_X(v.geom) - ST_X(s.geom)) * (111.41284 * cos(radians(ST_Y(s.geom)))
            - 0.0935 * cos(radians(3 * ST_Y(s.geom)))), 2))
"""


def _build_reach(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify each school, rank the reach list and roll up by LGA.

    Pure: takes already-fetched rows (one per school, with its nearest
    village and the 2 km ring counts), so the rules are testable without a
    database.

    * dark    — at least one village measured within 2 km and none lit or dim.
      A school in a lit town is never counted dark because of one unlit
      quarter beside it.
    * unknown — no village with a light reading within 2 km; not counted
      either way.
    * reach list — dark schools, one per village, most people first.
    """
    schools: list[ReachSchool] = []
    for r in rows:
        lit = int(r.get("lit_2km") or 0)
        measured = lit + int(r.get("unlit_2km") or 0)
        if not r.get("village") or measured == 0:
            light = "unknown"
        elif lit > 0:
            light = "lit"
        else:
            light = "dark"
        km = r.get("village_km")
        schools.append(ReachSchool(
            name=r["name"], category=r.get("category"), management=r.get("management"),
            lga=r.get("lga"), location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            light=light, village=r.get("village"), ward=r.get("ward"),
            village_km=round(float(km), 2) if km is not None else None,
            village_light=r.get("village_light"),
            people=r.get("people"), under5=r.get("under5"),
            villages_2km=int(r.get("villages_2km") or 0),
            lit_villages_2km=lit,
            people_2km=int(r.get("people_2km") or 0),
            under5_2km=int(r.get("under5_2km") or 0),
        ))

    # One school per village, the village with the most people first. The
    # village key is its GRID3 settlement id (names repeat across LGAs).
    keyed = [(sc, r.get("settlement_id")) for sc, r in zip(schools, rows) if sc.light == "dark"]
    keyed.sort(key=lambda sk: (-(sk[0].people or 0), sk[0].name))
    seen: set[Any] = set()
    people = under5 = 0
    for sc, key in keyed:
        if key in seen:
            continue
        seen.add(key)
        sc.rank = len(seen)
        people += sc.people or 0
        under5 += sc.under5 or 0

    by_lga: dict[str, list[int]] = {}
    for sc in schools:
        tally = by_lga.setdefault(sc.lga or "Unknown", [0, 0, 0])
        tally[0] += 1
        tally[1] += sc.light != "unknown"
        tally[2] += sc.light == "dark"
    lgas = [
        ReachLga(lga=lga, schools=n, assessed=a, dark=d,
                 dark_pct=round(100 * d / a, 1) if a else None)
        for lga, (n, a, d) in by_lga.items()
    ]
    lgas.sort(key=lambda g: (-(g.dark_pct if g.dark_pct is not None else -1.0), g.lga))

    assessed = sum(1 for sc in schools if sc.light != "unknown")
    dark = sum(1 for sc in schools if sc.light == "dark")
    return {
        "schools": len(schools), "assessed": assessed, "dark": dark,
        "dark_pct": round(100 * dark / assessed, 1) if assessed else None,
        "primary": sum(1 for sc in schools if sc.category == "Primary"),
        "secondary": sum(1 for sc in schools if sc.category == "Secondary"),
        "dark_villages": len(seen), "people": people, "under5": under5,
        "lgas": lgas, "rows": schools,
    }


@router.get(
    "/reach",
    response_model=SuccessResponse[SchoolReachData],
    summary="Every mapped school: is there light at night within 2 km, and who lives there",
)
async def school_reach(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[SchoolReachData]:
    """The school reach list — the schools to power and connect first.

    Schools from the GRID3 school register (public.school_register, 0057);
    night light and people from the village layer (village_light, 0054:
    NASA VIIRS Black Marble + Meta & CIESIN HRSL at GRID3 villages). Light
    visible from space is not a measure of a school's own supply: "dark"
    means no village within 2 km shows light the satellite can detect.
    """
    tenant_id = _require_tenant(request)
    meta = ResponseMeta(
        tenant_id=None, trace_id=_trace_id(request),
        timestamp=datetime.now(timezone.utc), pagination=None,
    )
    state = GRID3_STATE.get(tenant_id)
    if state is None:
        return SuccessResponse(data=SchoolReachData(
            reason="The GRID3 school register covers Nigeria; this pilot is not in it yet.",
        ), meta=meta)

    ready = (await session.execute(text(
        "SELECT to_regclass('public.school_register') IS NOT NULL "
        "AND to_regclass('village_light') IS NOT NULL"
    ))).scalar()
    period_row = None
    if ready:
        period_row = (await session.execute(text(
            """
            SELECT period, max(dry_window) AS dry_window FROM village_light
             WHERE period = (SELECT max(period) FROM village_light)
             GROUP BY period
            """
        ))).mappings().first()
    if period_row is None:
        return SuccessResponse(data=SchoolReachData(
            state=state,
            reason="Night light has not been measured at this state's villages yet.",
        ), meta=meta)

    # One pass per school: every village of the latest round within 2 km,
    # its nearest one first.
    rows = (await session.execute(text(
        f"""
        SELECT s.name, s.category, s.management, s.lga,
               ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat, ring.*
          FROM public.school_register s
          LEFT JOIN LATERAL (
              SELECT (array_agg(c.settlement_id ORDER BY c.km))[1] AS settlement_id,
                     (array_agg(c.name ORDER BY c.km))[1] AS village,
                     (array_agg(c.ward ORDER BY c.km))[1] AS ward,
                     (array_agg(c.light_class ORDER BY c.km))[1] AS village_light,
                     (array_agg(c.people ORDER BY c.km))[1] AS people,
                     (array_agg(c.under5 ORDER BY c.km))[1] AS under5,
                     min(c.km) AS village_km,
                     count(*) AS villages_2km,
                     count(*) FILTER (WHERE c.light_class IN ('lit', 'dim')) AS lit_2km,
                     count(*) FILTER (WHERE c.light_class = 'unlit') AS unlit_2km,
                     coalesce(sum(c.people), 0) AS people_2km,
                     coalesce(sum(c.under5), 0) AS under5_2km
                FROM (SELECT v.settlement_id, v.name, v.ward, v.light_class,
                             v.people, v.under5, {_KM} AS km
                        FROM village_light v
                       WHERE v.period = :period
                         AND v.geom && ST_Expand(s.geom, :box)) c
               WHERE c.km <= :radius
          ) ring ON TRUE
         WHERE s.state = :state
         ORDER BY s.lga, s.name
        """
    ), {"period": period_row["period"], "box": REACH_BOX_DEG,
        "radius": REACH_RADIUS_KM, "state": state})).mappings().all()

    if not rows:
        return SuccessResponse(data=SchoolReachData(
            state=state, light_round=str(period_row["period"]),
            reason="The GRID3 school register has not been loaded for this state yet.",
        ), meta=meta)
    return SuccessResponse(data=SchoolReachData(
        available=True, state=state, light_round=str(period_row["period"]),
        light_window=period_row["dry_window"], **_build_reach(list(rows)),
    ), meta=meta)
