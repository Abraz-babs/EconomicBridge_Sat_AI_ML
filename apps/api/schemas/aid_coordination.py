"""Pydantic schemas for Module 02 — Aid Coordination Bridge."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


CoverageStatus = Literal["gap", "covered", "duplicated"]


class AidAgency(BaseModel):
    """One row from public.aid_agencies."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    sector: str
    country: str | None = None


class AgencyCoverageSummary(BaseModel):
    """Per-agency rollup for a tenant: which LGAs + total beneficiaries."""

    agency_slug: str
    agency_name: str
    sector: str
    lgas_covered: list[str] = Field(default_factory=list)
    beneficiaries_served: int


class LgaPoint(BaseModel):
    """One LGA with its coverage status + map centroid."""

    lga: str
    lon: float
    lat: float
    agency_count: int
    status: CoverageStatus
    agency_slugs: list[str] = Field(default_factory=list)


class CoverageMatrixRow(BaseModel):
    """One row of the agency × LGA grid (1 = covered, 0 = not)."""

    agency_slug: str
    agency_name: str
    row: list[int] = Field(default_factory=list)


class AidCoordinationStats(BaseModel):
    """Full payload of GET /api/v1/aid_coordination/coverage."""

    tenant_id: str
    active_agencies: int
    total_lgas: int
    covered_lgas: int
    coverage_pct: float
    duplication_pct: float          # % of LGAs with 2+ agencies
    gap_lgas: list[str] = Field(default_factory=list)
    agencies: list[AgencyCoverageSummary] = Field(default_factory=list)
    matrix: list[CoverageMatrixRow] = Field(default_factory=list)
    lga_columns: list[str] = Field(default_factory=list)
    lga_points: list[LgaPoint] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ─── Admin upload contract ────────────────────────────────────────────────


class AidCoverageUploadRequest(BaseModel):
    """Body of POST /api/v1/aid_coordination/coverage.

    Single (agency, LGA) row — bulk CSV ingestion arrives in a follow-
    up slice once the operator's data-supply chain (WFP SCOPE export
    pipeline) is wired.
    """

    model_config = ConfigDict(extra="forbid")

    agency_slug: str = Field(min_length=1, max_length=40)
    lga: str = Field(min_length=1, max_length=120)
    beneficiaries_served: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    last_active_at: date | None = None
    source: Annotated[str, Field(min_length=1, max_length=40)] = "manual_admin"


class AidCoverageRow(BaseModel):
    """One row from tenant_<id>.aid_coverage — returned after insert."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    agency_slug: str
    agency_name: str | None = None
    lga: str
    beneficiaries_served: int
    last_active_at: date | None
    source: str
    created_at: datetime
    updated_at: datetime


# ─── Bulk CSV upload contract ─────────────────────────────────────────────


class BulkCoverageRowError(BaseModel):
    """One row that couldn't be ingested. Reported back to the operator
    alongside the successful upsert count."""

    line_number: int                    # 1-based, includes header line
    raw_row: dict[str, str]             # exactly what was in the CSV cell
    error: str                          # human-readable reason


class BulkCoverageUploadResult(BaseModel):
    """Summary returned from POST /aid_coordination/coverage/bulk."""

    tenant_id: str
    source: str                         # tagged on every row inserted
    rows_received: int                  # total CSV data rows (excludes header)
    rows_inserted: int                  # upserts that landed (new + updated)
    rows_skipped: int                   # rows rejected — see errors list
    errors: list[BulkCoverageRowError] = Field(default_factory=list)
