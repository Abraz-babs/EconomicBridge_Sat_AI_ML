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

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.poverty import LonLat, PovertyStatsData, PovertyVillage


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
