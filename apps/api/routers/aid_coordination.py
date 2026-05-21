"""GET  /api/v1/aid_coordination/coverage — Module 02 aggregate view.
POST /api/v1/aid_coordination/coverage — admin upload one agency/LGA row.

Read endpoint joins `tenant_<id>.aid_coverage` with `public.aid_agencies`
on slug, rolls up into the aggregate stats the dashboard needs (agencies
list, coverage matrix, gap/duplication metrics, per-LGA points with
deterministic spiral centroids around the tenant ROI).

Admin upload performs UPSERT on (agency_slug, lga, source) so re-imports
from the same partner-org pipeline replace cleanly. NEMA/WFP/UNHCR
bulk-CSV ingestion arrives in a follow-up slice.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from schemas.aid_coordination import (
    AgencyCoverageSummary,
    AidCoordinationStats,
    AidCoverageRow,
    AidCoverageUploadRequest,
    CoverageMatrixRow,
    CoverageStatus,
    LgaPoint,
)
from schemas.envelope import ResponseMeta, SuccessResponse


router = APIRouter(prefix="/aid_coordination", tags=["aid-coordination"])


# Tenant centroids (mirror apps/frontend/src/data/tenants.ts) — used
# to lay LGA points out in a deterministic spiral around the centre.
TENANT_CENTROIDS: dict[str, tuple[float, float]] = {
    "kebbi":    (4.55, 12.00),
    "benue":    (8.85, 7.20),
    "plateau":  (9.25, 9.45),
    "kaduna":   (8.15, 10.40),
    "niger":    (5.50, 10.30),
    "zamfara":  (6.50, 12.30),
    "nasarawa": (8.40, 8.85),
    "fct":      (7.49, 9.06),
    "ghana":    (-1.10, 7.95),
    "senegal":  (-14.45, 14.50),
}


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


def _lga_centroid(
    tenant_id: str, idx: int, total: int,
) -> tuple[float, float]:
    """Deterministic spiral fan around the tenant centre — matches the
    frontend's coordinationStatsFor(...).lga_points geometry exactly."""
    cx, cy = TENANT_CENTROIDS.get(tenant_id, (0.0, 0.0))
    if total <= 0:
        return cx, cy
    angle = (idx * 360.0 / total) * math.pi / 180.0
    radius = 0.45 + (idx % 3) * 0.18
    lon = cx + math.cos(angle) * radius
    lat = cy + math.sin(angle) * radius * 0.85
    return lon, lat


# ─── GET aggregate ────────────────────────────────────────────────────────


@router.get(
    "/coverage",
    response_model=SuccessResponse[AidCoordinationStats],
    summary="Aggregate agency × LGA coverage for the active tenant",
)
async def get_coverage(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AidCoordinationStats]:
    tenant_id = _require_tenant(request)

    # Join coverage rows (tenant schema) with the agency registry (public)
    # by slug. Cross-schema reads work fine because the tenant middleware
    # already set search_path = tenant_<id>, public.
    result = await session.execute(
        text(
            """
            SELECT c.agency_slug,
                   c.lga,
                   c.beneficiaries_served,
                   c.source,
                   a.name        AS agency_name,
                   a.sector      AS sector
              FROM aid_coverage c
              LEFT JOIN public.aid_agencies a
                   ON a.slug = c.agency_slug
             ORDER BY c.agency_slug, c.lga
            """
        ),
    )
    rows = result.mappings().all()

    if not rows:
        # Empty tenant — return zero state with no LGAs computed.
        return SuccessResponse(
            data=AidCoordinationStats(
                tenant_id=tenant_id, active_agencies=0, total_lgas=0,
                covered_lgas=0, coverage_pct=0.0, duplication_pct=0.0,
            ),
            meta=ResponseMeta(
                tenant_id=None, trace_id=_trace_id(request),
                timestamp=datetime.now(timezone.utc), pagination=None,
            ),
        )

    # Roll up — per-agency, per-LGA, sources.
    agency_to_lgas: dict[str, set[str]] = {}
    agency_to_meta: dict[str, dict[str, str]] = {}
    agency_to_beneficiaries: dict[str, int] = {}
    lga_to_agencies: dict[str, list[str]] = {}
    sources: set[str] = set()

    for r in rows:
        slug = r["agency_slug"]
        lga = r["lga"]
        agency_to_lgas.setdefault(slug, set()).add(lga)
        agency_to_meta[slug] = {
            "name": r.get("agency_name") or slug,
            "sector": r.get("sector") or "unknown",
        }
        agency_to_beneficiaries[slug] = agency_to_beneficiaries.get(slug, 0) + int(
            r["beneficiaries_served"] or 0
        )
        lga_to_agencies.setdefault(lga, []).append(slug)
        sources.add(r["source"])

    # Stable orderings.
    agency_slugs_sorted = sorted(agency_to_lgas.keys())
    lga_columns = sorted(lga_to_agencies.keys())

    # Matrix
    matrix = [
        CoverageMatrixRow(
            agency_slug=slug,
            agency_name=agency_to_meta[slug]["name"],
            row=[1 if lga in agency_to_lgas[slug] else 0 for lga in lga_columns],
        )
        for slug in agency_slugs_sorted
    ]

    # Per-agency summary
    agencies = [
        AgencyCoverageSummary(
            agency_slug=slug,
            agency_name=agency_to_meta[slug]["name"],
            sector=agency_to_meta[slug]["sector"],
            lgas_covered=sorted(agency_to_lgas[slug]),
            beneficiaries_served=agency_to_beneficiaries[slug],
        )
        for slug in agency_slugs_sorted
    ]

    # LGA points with status + spiral centroid
    lga_points: list[LgaPoint] = []
    for idx, lga in enumerate(lga_columns):
        slugs_here = lga_to_agencies[lga]
        count = len(slugs_here)
        status_: CoverageStatus = (
            "gap" if count == 0 else "covered" if count == 1 else "duplicated"
        )
        lon, lat = _lga_centroid(tenant_id, idx, len(lga_columns))
        lga_points.append(LgaPoint(
            lga=lga, lon=lon, lat=lat,
            agency_count=count,
            status=status_,
            agency_slugs=sorted(slugs_here),
        ))

    covered_lgas = sum(1 for p in lga_points if p.agency_count > 0)
    dup_lgas = sum(1 for p in lga_points if p.agency_count > 1)
    gap_lgas = [p.lga for p in lga_points if p.agency_count == 0]

    return SuccessResponse(
        data=AidCoordinationStats(
            tenant_id=tenant_id,
            active_agencies=len(agency_slugs_sorted),
            total_lgas=len(lga_columns),
            covered_lgas=covered_lgas,
            coverage_pct=(covered_lgas / len(lga_columns)) * 100,
            duplication_pct=(dup_lgas / len(lga_columns)) * 100,
            gap_lgas=gap_lgas,
            agencies=agencies,
            matrix=matrix,
            lga_columns=lga_columns,
            lga_points=lga_points,
            sources=sorted(sources),
        ),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )


# ─── POST admin upload ────────────────────────────────────────────────────


@router.post(
    "/coverage",
    response_model=SuccessResponse[AidCoverageRow],
    status_code=status.HTTP_201_CREATED,
    summary="Admin: upsert one agency × LGA coverage row",
)
async def upload_coverage(
    body: AidCoverageUploadRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AidCoverageRow]:
    """Admin path for manual or partner-bulk imports.

    UPSERTs on (agency_slug, lga, source) so re-running the same import
    replaces the row cleanly. Different sources (manual_admin vs
    wfp_scope_v1) coexist for audit.

    Validates that agency_slug exists in the public registry — typos in
    a bulk upload would otherwise silently create orphan coverage rows.
    """
    tenant_id = _require_tenant(request)

    agency_check = await session.execute(
        text("SELECT name FROM public.aid_agencies WHERE slug = :slug"),
        {"slug": body.agency_slug},
    )
    agency_row = agency_check.mappings().first()
    if agency_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Unknown agency_slug {body.agency_slug!r}. Register it "
                "in public.aid_agencies first."
            ),
        )

    upsert = await session.execute(
        text(
            """
            INSERT INTO aid_coverage (
                tenant_id, agency_slug, lga,
                beneficiaries_served, last_active_at, source
            ) VALUES (
                :tenant_id, :agency_slug, :lga,
                :beneficiaries, :last_active, :source
            )
            ON CONFLICT (agency_slug, lga, source) DO UPDATE
              SET beneficiaries_served = EXCLUDED.beneficiaries_served,
                  last_active_at = EXCLUDED.last_active_at,
                  updated_at = NOW()
            RETURNING id, tenant_id, agency_slug, lga,
                      beneficiaries_served, last_active_at,
                      source, created_at, updated_at
            """
        ),
        {
            "tenant_id": tenant_id,
            "agency_slug": body.agency_slug,
            "lga": body.lga,
            "beneficiaries": body.beneficiaries_served,
            "last_active": body.last_active_at,
            "source": body.source,
        },
    )
    row = upsert.mappings().one()
    await session.commit()

    return SuccessResponse(
        data=AidCoverageRow(
            id=row["id"],
            tenant_id=row["tenant_id"],
            agency_slug=row["agency_slug"],
            agency_name=agency_row["name"],
            lga=row["lga"],
            beneficiaries_served=int(row["beneficiaries_served"]),
            last_active_at=row["last_active_at"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ),
        meta=ResponseMeta(
            tenant_id=None, trace_id=_trace_id(request),
            timestamp=datetime.now(timezone.utc), pagination=None,
        ),
    )
