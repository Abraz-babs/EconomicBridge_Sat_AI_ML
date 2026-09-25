"""GET /api/v1/economic_visibility/villages — Module 01 (Poverty Mapping).

Read-only consumer of `tenant_<id>.poverty_villages` (migration 0018).
The X-Tenant-Id header selects the tenant — middleware/tenant.py sets
search_path so the bare table name resolves to the right schema.

Returns the full village list plus pre-aggregated stats (coverage %,
DHS verification %, population estimate, unreached households) so the
dashboard renders without doing the rollup math client-side.

Real VIIRS/WorldPop ingestion lands in a follow-up slice. Until then
rows are populated via `python -m scripts.seed_poverty_villages` and
tagged source='seed_v1'.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.poverty import (
    LgaLightRow,
    LonLat,
    PovertyStatsData,
    PovertyVillage,
    UnlitVillage,
    VillageLightData,
    VillageLightStats,
)


router = APIRouter(prefix="/economic_visibility", tags=["economic-visibility"])


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


@router.get(
    "/villages",
    response_model=SuccessResponse[PovertyStatsData],
    summary="List poverty-mapped villages + aggregate stats for a tenant",
    description=(
        "Returns rows from `tenant_<id>.poverty_villages`. X-Tenant-Id "
        "is required. Optional `limit` caps the village list (default "
        "200 — enough to cover a state-level ROI without paging)."
    ),
)
async def list_villages(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=2000, description="Max villages returned.")
    ] = 1000,
) -> SuccessResponse[PovertyStatsData]:
    tenant_id = _require_tenant(request)

    # LEFT JOIN raster_samples for the latest WorldPop sample per village.
    # Matches on (settlement_name, source) — the sampler writes
    # linked_settlement_name=settlement_name so the join is cheap and
    # doesn't require recomputing ST_DWithin on every dashboard hit.
    result = await session.execute(
        text(
            """
            SELECT * FROM (
                -- One row per settlement, preferring a live source
                -- (viirs_v2 / worldpop_v1) over seed_v1, newest first — so a
                -- settlement that has been ingested live shows once, not as
                -- duplicate seed + live pins (Slice 34).
                SELECT DISTINCT ON (v.lga, v.settlement_name)
                   v.id, v.tenant_id, v.settlement_name, v.lga,
                   ST_X(v.location) AS lon, ST_Y(v.location) AS lat,
                   v.poverty_score, v.population, v.households_unreached,
                   v.nightlight_dimness, v.has_dhs_data,
                   v.viirs_pixel_radiance, v.worldpop_estimate,
                   v.source, v.created_at, v.updated_at,
                   wp.value       AS latest_worldpop_sample,
                   wp.captured_at AS worldpop_sampled_at
                  FROM poverty_villages v
                  LEFT JOIN LATERAL (
                      SELECT value, captured_at
                        FROM raster_samples r
                       WHERE r.linked_settlement_name = v.settlement_name
                         AND r.source = 'worldpop_ppp_v1'
                         AND r.valid = TRUE
                       ORDER BY r.captured_at DESC
                       LIMIT 1
                  ) wp ON TRUE
                 ORDER BY v.lga, v.settlement_name,
                          CASE WHEN v.source = 'seed_v1' THEN 9 ELSE 0 END,
                          v.updated_at DESC
            ) deduped
             ORDER BY poverty_score DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()

    villages = [
        PovertyVillage(
            id=r["id"],
            tenant_id=r["tenant_id"],
            settlement_name=r["settlement_name"],
            lga=r["lga"],
            location=LonLat(lon=float(r["lon"]), lat=float(r["lat"])),
            poverty_score=float(r["poverty_score"]),
            population=int(r["population"]),
            households_unreached=int(r["households_unreached"]),
            nightlight_dimness=float(r["nightlight_dimness"]),
            has_dhs_data=bool(r["has_dhs_data"]),
            viirs_pixel_radiance=(
                float(r["viirs_pixel_radiance"])
                if r.get("viirs_pixel_radiance") is not None else None
            ),
            worldpop_estimate=(
                float(r["worldpop_estimate"])
                if r.get("worldpop_estimate") is not None else None
            ),
            latest_worldpop_sample=(
                float(r["latest_worldpop_sample"])
                if r.get("latest_worldpop_sample") is not None else None
            ),
            worldpop_sampled_at=r.get("worldpop_sampled_at"),
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    # Pre-aggregate so the dashboard isn't doing the rollup math.
    total_pop = sum(v.population for v in villages)
    total_unreached = sum(v.households_unreached for v in villages)
    # Coverage proxy: 1 - (4 × unreached / pop) — same formulation as
    # the old frontend seed (one household ≈ 4 people).
    coverage = max(0.0, 1.0 - (4 * total_unreached / max(total_pop, 1)))
    verified = (
        sum(1 for v in villages if v.has_dhs_data) / max(len(villages), 1)
    )
    sources = sorted({v.source for v in villages})

    raster_sampled = sum(
        1 for v in villages if v.latest_worldpop_sample is not None
    )
    # Real WorldPop pixel reads are a genuine LIVE source feeding this page
    # (population enrichment), even though the settlement rows themselves stay
    # modelled — surface it so the provenance badge reflects the blend instead
    # of reading DEMO forever.
    if raster_sampled > 0 and "worldpop_cog_v1" not in sources:
        sources.append("worldpop_cog_v1")

    return SuccessResponse(
        data=PovertyStatsData(
            tenant_id=tenant_id,
            villages_identified=len(villages),
            population_estimated=total_pop,
            households_unreached=total_unreached,
            coverage_pct=coverage * 100,
            verification_pct=verified * 100,
            raster_sampled_villages=raster_sampled,
            villages=villages,
            sources=sources,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


# ─── Village light — measured night light and people at real villages ─────

_CLASS_CODE = {"unlit": 0, "dim": 1, "lit": 2, "unknown": 3}


@router.get(
    "/village-light",
    response_model=SuccessResponse[VillageLightData],
    summary="Which real villages are dark at night, and who lives there",
    description=(
        "Every GRID3-named village of the tenant for one measurement round: "
        "VIIRS night light (dry season, with a wet-season check), HRSL people "
        "and children under five, the LGA table and every village for the map. "
        "Omit `period` for the latest round."
    ),
)
async def village_light(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    period: Annotated[str | None, Query(max_length=16)] = None,
    top: Annotated[int, Query(ge=1, le=200)] = 25,
) -> SuccessResponse[VillageLightData]:
    _require_tenant(request)

    def reply(data: VillageLightData) -> SuccessResponse[VillageLightData]:
        return SuccessResponse(data=data, meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request), timestamp=datetime.now(timezone.utc)))

    if not (await session.execute(text("SELECT to_regclass('village_light') IS NOT NULL"))).scalar():
        return reply(VillageLightData(period=None, periods=[]))
    periods = [r[0] for r in (await session.execute(text(
        "SELECT DISTINCT period FROM village_light ORDER BY period DESC"))).all()]
    chosen = period if period in periods else (periods[0] if periods else None)
    if chosen is None:
        return reply(VillageLightData(period=None, periods=[]))
    p = {"p": chosen}

    s = (await session.execute(text("""
        SELECT count(*),
               count(*) FILTER (WHERE light_class = 'unlit'),
               count(*) FILTER (WHERE light_class = 'dim'),
               count(*) FILTER (WHERE light_class = 'lit'),
               count(*) FILTER (WHERE light_class = 'unknown'),
               count(*) FILTER (WHERE light_class = 'unlit' AND light_class_wet = 'unlit'),
               COALESCE(sum(people), 0),
               COALESCE(sum(people) FILTER (WHERE light_class = 'unlit'), 0),
               COALESCE(sum(under5) FILTER (WHERE light_class = 'unlit'), 0),
               max(dry_window), max(wet_window), max(sources)
          FROM village_light WHERE period = :p
    """), p)).one()
    lgas = [LgaLightRow(lga=r[0] or "Unknown", villages=r[1], unlit=r[2],
                        people_unlit=r[3], under5_unlit=r[4])
            for r in (await session.execute(text("""
        SELECT lga, count(*),
               count(*) FILTER (WHERE light_class = 'unlit'),
               COALESCE(sum(people) FILTER (WHERE light_class = 'unlit'), 0),
               COALESCE(sum(under5) FILTER (WHERE light_class = 'unlit'), 0)
          FROM village_light WHERE period = :p
         GROUP BY lga ORDER BY 4 DESC
    """), p)).all()]
    top_rows = (await session.execute(text("""
        SELECT name, ward, lga, ST_X(geom), ST_Y(geom), people, under5,
               radiance_dry, radiance_wet, light_class_wet
          FROM village_light WHERE period = :p AND light_class = 'unlit'
         ORDER BY people DESC LIMIT :top
    """), {**p, "top": top})).all()
    points = [[round(r[0], 4), round(r[1], 4), _CLASS_CODE.get(r[2], 3), _CLASS_CODE.get(r[3], 3), r[4]]
              for r in (await session.execute(text(
                  "SELECT ST_X(geom), ST_Y(geom), light_class, light_class_wet, people "
                  "FROM village_light WHERE period = :p"), p)).all()]
    return reply(VillageLightData(
        period=chosen, periods=periods, dry_window=s[9], wet_window=s[10], sources=s[11],
        stats=VillageLightStats(villages=s[0], unlit=s[1], dim=s[2], lit=s[3], unknown=s[4],
                                unlit_both_seasons=s[5], people=s[6], people_unlit=s[7],
                                under5_unlit=s[8]),
        lgas=lgas,
        top_unlit=[UnlitVillage(name=r[0], ward=r[1], lga=r[2], location=LonLat(lon=r[3], lat=r[4]),
                                people=r[5], under5=r[6], radiance_dry=r[7], radiance_wet=r[8],
                                light_class_wet=r[9]) for r in top_rows],
        points=points,
    ))


# ─── Village reach list (CSV) ────────────────────────────────────────────

EXPORT_COLUMNS: tuple[str, ...] = (
    "rank", "village", "ward", "lga", "latitude", "longitude",
    "light_dry_season", "light_wet_season", "radiance_dry_nw", "radiance_wet_nw",
    "people_estimate", "under5_estimate", "directions", "round", "sources",
)


def export_rows(rows: list[tuple], period: str, sources: str | None) -> list[list]:
    """DB rows (name, ward, lga, lon, lat, class, class_wet, rad_dry, rad_wet,
    people, under5), already ordered, into CSV rows. Pure — no DB.

    People and under-fives are ESTIMATES (Meta & CIESIN HRSL), and the column
    names say so, because a field team will read this file without the panel's
    footnotes beside it.
    """
    out: list[list] = []
    for i, r in enumerate(rows, start=1):
        name, ward, lga, lon, lat, cls, cls_wet, rad_dry, rad_wet, people, under5 = r
        out.append([
            i, name, ward or "", lga or "", round(lat, 5), round(lon, 5),
            cls, cls_wet or "", rad_dry if rad_dry is not None else "",
            rad_wet if rad_wet is not None else "", people, under5,
            f"https://www.google.com/maps/dir/?api=1&destination={lat:.5f},{lon:.5f}",
            period, sources or "",
        ])
    return out


@router.get(
    "/village-light/export.csv",
    summary="Village reach list — every village of the tenant (or only unlit ones) as CSV",
    description=(
        "One row per GRID3 village for one measurement round, most people first: "
        "coordinates, night light in both seasons, estimated people and children "
        "under five, and a navigation link — for enumeration and field teams."
    ),
)
async def village_light_export(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    scope: Annotated[Literal["unlit", "all"], Query()] = "unlit",
    period: Annotated[str | None, Query(max_length=16)] = None,
) -> StreamingResponse:
    tenant_id = _require_tenant(request)
    if not (await session.execute(text("SELECT to_regclass('village_light') IS NOT NULL"))).scalar():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No village measurements yet")
    periods = [r[0] for r in (await session.execute(text(
        "SELECT DISTINCT period FROM village_light ORDER BY period DESC"))).all()]
    chosen = period if period in periods else (periods[0] if periods else None)
    if chosen is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No village measurements yet")
    where = "period = :p" + (" AND light_class = 'unlit'" if scope == "unlit" else "")
    rows = (await session.execute(text(f"""
        SELECT name, ward, lga, ST_X(geom), ST_Y(geom), light_class, light_class_wet,
               radiance_dry, radiance_wet, people, under5
          FROM village_light WHERE {where}
         ORDER BY people DESC, name
    """), {"p": chosen})).all()
    sources = (await session.execute(text(
        "SELECT max(sources) FROM village_light WHERE period = :p"), {"p": chosen})).scalar()

    buf = io.StringIO()
    buf.write("﻿")   # BOM: Excel then reads village names with accents correctly
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(export_rows([tuple(r) for r in rows], chosen, sources))
    fname = f"{tenant_id}_villages_{scope}_{chosen}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
