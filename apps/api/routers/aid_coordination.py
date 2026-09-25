"""GET  /api/v1/aid_coordination/coverage — Module 02 aggregate view.
POST /api/v1/aid_coordination/coverage — admin upload one agency/LGA row.

The read is built from REAL records only:

  * tenant_<id>.aid_activities — IATI activities published by the
    organisations themselves (migration 0055, ingestion task aid_iati_ingest):
    a row per activity location, with `lga` for a site inside the tenant and
    NULL for statewide (countrywide for Ghana / Senegal);
  * tenant_<id>.aid_coverage rows that are NOT seed fixtures — admin / partner
    uploads and HDX HAPI (`hapi_v1`).

Gaps are counted against EVERY LGA of the tenant (services/lga_geo), each
drawn at its real centre. Until 2026-09-25 this view read seed rows naming six
real organisations with invented coverage and beneficiary counts, counted only
LGAs that had rows (so coverage was 100% by construction) and fanned LGA
points in a spiral around the state centre. The seed rows stay stored (no
record is deleted) and are never read.

"Overlap" is two or more organisations working in the SAME sector in the same
LGA. An LGA with no reported activity is not an LGA with no aid: state
agencies and many NGOs do not publish to IATI.

Admin upload performs UPSERT on (agency_slug, lga, source).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
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
from services import lga_geo


router = APIRouter(prefix="/aid_coordination", tags=["aid-coordination"])

# Fabricated fixtures — stored, never shown.
SEED_SOURCE = "seed_v1"
IATI_ATTRIBUTION = "IATI data, via d-portal.org"
# Tenants that are whole countries: their area-wide activity is countrywide.
COUNTRY_TENANTS = frozenset({"ghana", "senegal"})


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


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One real record: an organisation active at a site (lga) or statewide (None)."""

    org_slug: str
    org_name: str
    lga: str | None
    sectors: tuple[str, ...]
    buckets: tuple[str, ...]
    activity: str
    source: str


@dataclass
class _Org:
    name: str
    lgas: set[str] = field(default_factory=set)
    sectors: list[str] = field(default_factory=list)
    activities: set[str] = field(default_factory=set)
    statewide: set[str] = field(default_factory=set)


def build_stats(
    tenant_id: str,
    lgas: list[str],
    centres: dict[str, tuple[float, float]],
    rows: list[ActivityRow],
) -> AidCoordinationStats:
    """Roll real activity rows up into the panel's stats. Pure — no DB."""
    lga_set = set(lgas)
    wide_label = "Countrywide" if tenant_id in COUNTRY_TENANTS else "Statewide"
    orgs: dict[str, _Org] = {}
    lga_orgs: dict[str, set[str]] = defaultdict(set)
    lga_bucket_orgs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    sources: set[str] = set()

    for r in rows:
        if r.lga is not None and r.lga not in lga_set:
            continue
        o = orgs.setdefault(r.org_slug, _Org(name=r.org_name))
        o.activities.add(r.activity)
        for s in r.sectors:
            if s and s not in o.sectors:
                o.sectors.append(s)
        sources.add(r.source)
        if r.lga is None:
            o.statewide.add(r.activity)
            continue
        o.lgas.add(r.lga)
        lga_orgs[r.lga].add(r.org_slug)
        for b in r.buckets or ("Other",):
            lga_bucket_orgs[r.lga][b].add(r.org_slug)

    overlap = {
        lga for lga, by_bucket in lga_bucket_orgs.items()
        if any(len(slugs) >= 2 for slugs in by_bucket.values())
    }
    slugs = sorted(orgs, key=lambda s: (-len(orgs[s].lgas), -len(orgs[s].activities), orgs[s].name))
    any_wide = any(orgs[s].statewide for s in slugs)
    columns = sorted(lgas) + ([wide_label] if any_wide else [])

    def cell(slug: str, column: str) -> int:
        if any_wide and column == wide_label:
            return 1 if orgs[slug].statewide else 0
        return 1 if column in orgs[slug].lgas else 0

    matrix = [
        CoverageMatrixRow(agency_slug=s, agency_name=orgs[s].name,
                          row=[cell(s, c) for c in columns])
        for s in slugs
    ]
    agencies = [
        AgencyCoverageSummary(
            agency_slug=s, agency_name=orgs[s].name,
            sector=", ".join(orgs[s].sectors[:3]) or "Sector not stated",
            lgas_covered=sorted(orgs[s].lgas),
            beneficiaries_served=None,
            activities=len(orgs[s].activities),
            statewide_activities=len(orgs[s].statewide),
        )
        for s in slugs
    ]
    points: list[LgaPoint] = []
    for lga in sorted(lgas):
        here = lga_orgs.get(lga, set())
        st: CoverageStatus = "gap" if not here else "duplicated" if lga in overlap else "covered"
        lon, lat = centres.get(lga, (0.0, 0.0))
        points.append(LgaPoint(lga=lga, lon=lon, lat=lat, agency_count=len(here),
                               status=st, agency_slugs=sorted(here)))

    total = len(lgas)
    covered = sum(1 for p in points if p.agency_count > 0)
    return AidCoordinationStats(
        tenant_id=tenant_id,
        active_agencies=len(slugs),
        total_lgas=total,
        covered_lgas=covered,
        coverage_pct=(covered / total * 100) if total else 0.0,
        duplication_pct=(len(overlap) / total * 100) if total else 0.0,
        gap_lgas=[p.lga for p in points if p.agency_count == 0],
        agencies=agencies,
        matrix=matrix,
        lga_columns=columns,
        lga_points=points,
        sources=sorted(sources),
        statewide_label=wide_label,
        statewide_orgs=sum(1 for s in slugs if orgs[s].statewide),
        attribution=IATI_ATTRIBUTION if "iati_v1" in sources else None,
    )


_CURRENT_ACTIVITIES = text("""
    SELECT org_slug, org_name, lga, sectors, sector_buckets, iati_id, source
      FROM aid_activities
     WHERE (start_date IS NULL OR start_date <= CURRENT_DATE)
       AND (end_date >= CURRENT_DATE
            OR (end_date IS NULL AND start_date >= CURRENT_DATE - INTERVAL '5 years'))
""")

_REAL_COVERAGE = text("""
    SELECT c.agency_slug, COALESCE(a.name, c.agency_slug) AS agency_name,
           c.lga, a.sector, c.source
      FROM aid_coverage c
      LEFT JOIN public.aid_agencies a ON a.slug = c.agency_slug
     WHERE COALESCE(c.source, '') <> :seed
""")


# ─── GET aggregate ────────────────────────────────────────────────────────


@router.get(
    "/coverage",
    response_model=SuccessResponse[AidCoordinationStats],
    summary="Who reports aid activity where, for the active tenant (real records only)",
)
async def get_coverage(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AidCoordinationStats]:
    tenant_id = _require_tenant(request)

    rows: list[ActivityRow] = []
    try:
        async with session.begin_nested():
            for r in (await session.execute(_CURRENT_ACTIVITIES)).mappings():
                rows.append(ActivityRow(
                    org_slug=r["org_slug"], org_name=r["org_name"], lga=r["lga"],
                    sectors=tuple(s.strip() for s in (r["sectors"] or "").split(";") if s.strip()),
                    buckets=tuple(r["sector_buckets"] or ()), activity=r["iati_id"],
                    source=r["source"],
                ))
    except ProgrammingError:
        # aid_activities not migrated yet on this database — show the rest.
        pass
    for r in (await session.execute(_REAL_COVERAGE, {"seed": SEED_SOURCE})).mappings():
        sector = (r["sector"] or "").strip()
        rows.append(ActivityRow(
            org_slug=r["agency_slug"], org_name=r["agency_name"], lga=r["lga"],
            sectors=(sector,) if sector else (), buckets=(sector or "Other",),
            activity=f'{r["source"]}:{r["agency_slug"]}:{r["lga"]}', source=r["source"],
        ))

    lgas = lga_geo.all_lgas(tenant_id)
    centres = {lga: lga_geo.centroid_for(tenant_id, lga) for lga in lgas}
    return SuccessResponse(
        data=build_stats(tenant_id, lgas, centres, rows),
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
