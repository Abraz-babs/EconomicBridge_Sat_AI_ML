"""POST /api/v1/claims/report — render a satellite claims verification report.

The browser runs the claim check per plot against the ingestion service
(POST /ingestion/api/v1/cropguard/claim-check) and posts the batch here; this
returns the PDF for the insurer. Super-admin only: every export is a paid
deliverable (standing rule), and in a pilot the operator runs and reviews each
batch before it leaves the company.

The results are taken as posted, so the report is only as trustworthy as the
person generating it — which is why this stays behind require_super_admin
rather than being opened to client accounts.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from dependencies import CurrentUser, require_super_admin
from services.claims_report import ClaimsBatch, ReportClaim, render_claims_report

router = APIRouter(prefix="/claims", tags=["claims"])

MAX_CLAIMS = 500


class ClaimCheckResult(BaseModel):
    """The ingestion claim-check response, as returned to the browser."""

    lat: float
    lon: float
    loss_date: str
    peril: Literal["flood", "drought", "general"]
    crop: str = "general"
    area_ha: float
    windows: dict[str, str]
    thresholds: dict[str, float]
    ndvi_passes: list[dict] = Field(default_factory=list)
    water_passes: list[dict] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    flood_evidence: str
    vegetation_change: str
    conclusion: Literal["supports", "partly_supports", "not_supported", "inconclusive"]
    summary: str
    recommendation: str
    limitations: list[str] = Field(default_factory=list)
    source: str


class ClaimReportItem(BaseModel):
    claim_id: str = Field(min_length=1, max_length=60)
    insured_name: str | None = Field(default=None, max_length=120)
    location_note: str | None = Field(default=None, max_length=120,
                                      description="e.g. LGA and village, as the insurer records it")
    result: ClaimCheckResult


class ClaimsReportRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=120)
    batch_ref: str = Field(min_length=1, max_length=60)
    claims: list[ClaimReportItem] = Field(min_length=1, max_length=MAX_CLAIMS)


@router.post("/report", summary="Satellite claims verification report (PDF)")
async def claims_report(
    body: ClaimsReportRequest,
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> StreamingResponse:
    batch = ClaimsBatch(
        client_name=body.client_name,
        batch_ref=body.batch_ref,
        claims=[ReportClaim(claim_id=c.claim_id, insured_name=c.insured_name,
                            location_note=c.location_note, result=c.result.model_dump())
                for c in body.claims],
    )
    pdf = render_claims_report(batch)
    safe_ref = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in body.batch_ref)
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="claims_report_{safe_ref}.pdf"'},
    )
