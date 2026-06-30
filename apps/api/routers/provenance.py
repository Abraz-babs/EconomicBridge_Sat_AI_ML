"""GET /api/v1/provenance — data-source provenance + compute budget.

The auditable "how genuine is this?" answer in one payload, for the dashboard's
Data Sources panel and for answering partners (NASRDA, etc.): every module's
satellite source + product, provider, licence + commercial status, the exact
attribution string, whether the feed is live/real or modelled, and its refresh
cadence — plus the CDSE compute account the live feeds draw from.

Static, read-only, no tenant coupling: the catalog is the same platform-wide,
so the panel can render it on any tenant without a DB round-trip.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request

from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.provenance import ComputeBudget, FeedProvenance, ProvenanceData


router = APIRouter(prefix="/provenance", tags=["provenance"])


# ─── The catalog (static truth) ────────────────────────────────────────────
# Every entry is verified against what the platform actually pulls. Licences
# are the plain-language commercial status; attribution is the exact string the
# UI must display next to the layer.

_CATALOG: tuple[FeedProvenance, ...] = (
    FeedProvenance(
        module="Farmland Protection",
        signal="Encroachment & land-disturbance risk (per LGA)",
        satellites=["Sentinel-1 SAR", "Sentinel-2 NDVI", "NASA FIRMS"],
        provider="Copernicus (ESA/EU) + NASA",
        license="Copernicus: free, full & open — commercial OK. NASA FIRMS: public domain.",
        attribution="Contains modified Copernicus Sentinel data 2026; NASA FIRMS (LANCE/EOSDIS).",
        kind="live",
        cadence="Daily, every LGA refreshed on the ~6-day Sentinel revisit (rolling).",
        method="CDSE Statistical API, per-LGA NDVI + SAR fusion.",
    ),
    FeedProvenance(
        module="Economic Visibility",
        signal="Night-light poverty mapping",
        satellites=["VIIRS Black Marble (VNP46A2)", "WorldPop"],
        provider="NASA LAADS DAAC + WorldPop",
        license="NASA: public domain — commercial OK. WorldPop: CC-BY 4.0 — commercial OK.",
        attribution="NASA Black Marble VNP46A2, LAADS DAAC; WorldPop (worldpop.org).",
        kind="live",
        cadence="Weekly; daily granules ~1 week behind real time.",
        method="Per-pixel HDF5 radiance read from the gap-filled DNB grid.",
    ),
    FeedProvenance(
        module="CropGuard",
        signal="Crop disease + per-field vegetation health",
        satellites=["Sentinel-2 NDVI", "Sentinel-1 SAR", "ResNet-50 classifier"],
        provider="Copernicus + EconomicBridge model",
        license="Copernicus: free & open — commercial OK. Classifier is our own model.",
        attribution="Contains modified Copernicus Sentinel data 2026; EconomicBridge ResNet-50.",
        kind="live",
        cadence="On-demand (Farm Check coordinates + leaf-photo uploads).",
        method="CDSE Statistical API + trained ResNet-50 (87% val accuracy).",
    ),
    FeedProvenance(
        module="ShockGuard",
        signal="Flood (SAR drop) + drought (NDVI drop) detection",
        satellites=["Sentinel-1 SAR", "Sentinel-2 NDVI"],
        provider="Copernicus (ESA/EU)",
        license="Copernicus: free, full & open — commercial OK.",
        attribution="Contains modified Copernicus Sentinel data 2026.",
        kind="live",
        cadence="Daily scan over the satellite-observations time series.",
        method="CDSE Statistical API + z-score anomaly detector.",
    ),
    FeedProvenance(
        module="Economic Mobility",
        signal="Income & employment anchor",
        satellites=["World Bank indicators", "Nigeria NLSS"],
        provider="World Bank + NBS Nigeria",
        license="World Bank Open Data: CC-BY 4.0 — commercial OK.",
        attribution="World Bank Open Data; Nigeria National Living Standards Survey.",
        kind="live",
        cadence="Monthly.",
        method="Keyless World Bank API + NLSS calibration.",
    ),
    FeedProvenance(
        module="SkillsBridge",
        signal="School access & connectivity",
        satellites=["UNICEF GIGA"],
        provider="UNICEF GIGA",
        license="GIGA: verify per-country terms before commercial reuse.",
        attribution="UNICEF GIGA (giga.global).",
        kind="live",
        cadence="Monthly.",
        method="GIGA school-location API.",
    ),
    FeedProvenance(
        module="Aid Coordination",
        signal="Humanitarian operational presence & coverage",
        satellites=["OCHA HDX HAPI"],
        provider="UN OCHA",
        license="HDX HAPI: per-dataset terms — verify before commercial reuse.",
        attribution="OCHA Humanitarian Data Exchange (HAPI).",
        kind="live",
        cadence="Monthly.",
        method="Keyless HDX HAPI.",
    ),
)

_COMPUTE = ComputeBudget(
    provider="Copernicus Data Space Ecosystem (CDSE)",
    tier="General (free)",
    monthly_pu=30000,
    monthly_requests=30000,
    note=(
        "Live Sentinel feeds draw on the free CDSE General allowance "
        "(30,000 Processing Units + 30,000 requests/month). Per-LGA coverage is "
        "revisit-matched (~4.5k PU/month) to stay well inside it. Commercial use "
        "is permitted under the Copernicus open-data policy with attribution."
    ),
)

_SUMMARY = (
    "All satellite layers are read live from public NASA (LAADS DAAC) and "
    "Copernicus (CDSE) sources under open-data licences that permit commercial "
    "use with attribution. No simulated or placeholder satellite values."
)


@router.get(
    "",
    response_model=SuccessResponse[ProvenanceData],
    summary="Data-source provenance, licences + compute budget (the 'how genuine' view)",
)
async def get_provenance(request: Request) -> SuccessResponse[ProvenanceData]:
    return SuccessResponse(
        data=ProvenanceData(
            feeds=list(_CATALOG), compute=_COMPUTE, summary=_SUMMARY,
        ),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=getattr(request.state, "trace_id", uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
    )
