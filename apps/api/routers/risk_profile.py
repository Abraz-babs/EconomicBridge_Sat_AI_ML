"""Pre-season risk profile — CropGuard's insurer section (approved 2026-10-10).

GET  /api/v1/cropguard/risk-profile             the latest round for the active state
GET  /api/v1/cropguard/risk-profile/export.csv  every figure, one row per LGA   (super-admin)
POST /api/v1/cropguard/risk-profile/report      the letterhead PDF               (super-admin)

Viewing is for the platform operator and insurer accounts (tenant category
"insurer"); downloads are paid deliverables and stay super-admin only, like
every export (standing rule). Reads tenant_<id>.lga_risk_profile and
risk_overlay (migration 0061) through the pinned search_path (X-Tenant-Id).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from dependencies import CurrentUser, require_insurance_viewer, require_super_admin
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.risk_profile import RiskLga, RiskOverlay, RiskProfileData, RiskSummary
from services.risk_profile import RULE, csv_text, filename, summarise
from services.risk_profile_report import RiskReport, render_risk_report

router = APIRouter(prefix="/cropguard/risk-profile", tags=["cropguard"])

METHOD = "risk_profile_v1"


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="X-Tenant-Id header is required for this endpoint")
    return tenant_id


def _meta(request: Request) -> ResponseMeta:
    return ResponseMeta(tenant_id=None, trace_id=getattr(request.state, "trace_id", uuid4()),
                        timestamp=datetime.now(timezone.utc), pagination=None)


async def load_round(session: AsyncSession) -> tuple[int | None, list[dict], list[dict]]:
    """(through_season, rows, overlays) of the latest round, or (None, [], [])."""
    if not (await session.execute(text("SELECT to_regclass('lga_risk_profile') IS NOT NULL"))).scalar():
        return None, [], []
    through = (await session.execute(text(
        "SELECT max(through_season) FROM lga_risk_profile WHERE method = :m"), {"m": METHOD})).scalar()
    if through is None:
        return None, [], []
    rows = [dict(r) for r in (await session.execute(text(
        "SELECT lga, band_flood, band_drought, band_rains, figures, sources, measured_at FROM lga_risk_profile "
        "WHERE through_season = :t AND method = :m ORDER BY lga"), {"t": through, "m": METHOD})).mappings().all()]
    for r in rows:
        if isinstance(r["figures"], str):
            r["figures"] = json.loads(r["figures"])
    overlays = [dict(r) for r in (await session.execute(text(
        "SELECT layer, label, west, south, east, north, png FROM risk_overlay "
        "WHERE through_season = :t AND method = :m ORDER BY layer"), {"t": through, "m": METHOD})).mappings().all()]
    return through, rows, overlays


@router.get("", response_model=SuccessResponse[RiskProfileData],
            summary="Pre-season risk profile of every LGA in the active state")
async def risk_profile(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _viewer: Annotated[CurrentUser, Depends(require_insurance_viewer)],
) -> SuccessResponse[RiskProfileData]:
    _tenant(request)
    through, rows, overlays = await load_round(session)
    if through is None or not rows:
        return SuccessResponse(data=RiskProfileData(available=False, rule=RULE), meta=_meta(request))
    rain0 = next((r["figures"].get("rain") for r in rows if r["figures"].get("rain")), None) or {}
    rains0 = next((r["figures"]["rains"] for r in rows if (r["figures"].get("rains") or {}).get("years")), None)
    data = RiskProfileData(
        available=True,
        through_season=through,
        first_season=rain0.get("first_year"),
        rains_first_season=rains0["years"][0] if rains0 else None,
        method=METHOD,
        measured_at=max(r["measured_at"] for r in rows),
        rule=RULE,
        summary=RiskSummary(**summarise(rows)),
        lgas=[RiskLga(lga=r["lga"], band_flood=r["band_flood"], band_drought=r["band_drought"],
                      band_rains=r["band_rains"], figures=r["figures"]) for r in rows],
        overlays=[RiskOverlay(layer=o["layer"], label=o["label"],
                              bounds=[o["west"], o["south"], o["east"], o["north"]],
                              image="data:image/png;base64," + base64.b64encode(bytes(o["png"])).decode())
                  for o in overlays],
        sources=rows[0]["sources"],
    )
    return SuccessResponse(data=data, meta=_meta(request))


@router.get("/export.csv", summary="Risk profile, every figure per LGA (CSV, super-admin)")
async def risk_profile_csv(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> StreamingResponse:
    tenant = _tenant(request)
    through, rows, _ = await load_round(session)
    if through is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No risk profile measured for this state yet.")
    body = csv_text(rows, through, METHOD)
    return StreamingResponse(iter([body.encode("utf-8-sig")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename(tenant, through, "csv")}"'})


class RiskReportRequest(BaseModel):
    prepared_for: str = Field(min_length=1, max_length=120)
    reference: str = Field(min_length=1, max_length=60)


@router.post("/report", summary="Pre-season risk profile report on the letterhead (PDF, super-admin)")
async def risk_profile_report(
    body: RiskReportRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> StreamingResponse:
    tenant = _tenant(request)
    through, rows, overlays = await load_round(session)
    if through is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No risk profile measured for this state yet.")
    name = (await session.execute(text("SELECT name FROM public.tenant_registry WHERE id = :t"),
                                  {"t": tenant})).scalar() or tenant.replace("_", " ").title()
    rep = RiskReport(
        prepared_for=body.prepared_for, reference=body.reference, state=name, through=through, method=METHOD,
        rows=rows, summary=summarise(rows),
        overlays={o["layer"]: {"bounds": [o["west"], o["south"], o["east"], o["north"]], "png": bytes(o["png"])}
                  for o in overlays},
    )
    pdf = render_risk_report(rep)
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{filename(tenant, through, "pdf")}"'})
