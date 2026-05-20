"""GET /api/v1/imagery/recent — live Sentinel scene metadata for a tenant.

Stateless STAC search against CDSE. We do NOT download the raster
products here — that's a separate concern (Phase A.6). This endpoint
answers "what Sentinel data is available for {tenant} in the last
{days} days?" which is enough to drive the dashboard's data-recency
indicators.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from db import is_valid_tenant_id
from sources.copernicus import CopernicusClient, CopernicusError
from sources.nasa_firms import PILOT_BBOX

router = APIRouter(prefix="/imagery", tags=["imagery"])


# Supported STAC collections (mirrors what CDSE actually serves under
# the catalog we point at).
SUPPORTED_COLLECTIONS: frozenset[str] = frozenset(
    {"sentinel-2-l2a", "sentinel-1-grd", "sentinel-3-olci-l1b"}
)


# ─── Response schemas ──────────────────────────────────────────────────────


class SceneResponse(BaseModel):
    scene_id: str
    collection: str
    captured_at: datetime
    cloud_cover_pct: float | None
    mgrs_tile: str | None
    bbox_west: float
    bbox_south: float
    bbox_east: float
    bbox_north: float
    self_href: str | None


class ImageryRecentResponse(BaseModel):
    tenant_id: str
    collection: str
    days: int
    bbox: list[float]
    max_cloud_cover_pct: float | None
    total: int
    scenes: list[SceneResponse]


# ─── Endpoint ──────────────────────────────────────────────────────────────


@router.get(
    "/recent",
    response_model=ImageryRecentResponse,
    summary="Recent Sentinel scenes covering a tenant ROI",
)
async def recent_imagery(
    tenant_id: str = Query(min_length=1, max_length=50),
    days: int = Query(default=7, ge=1, le=30),
    collection: str = Query(default="sentinel-2-l2a"),
    max_cloud_cover: float | None = Query(
        default=None,
        ge=0,
        le=100,
        description=(
            "Drop scenes whose eo:cloud_cover exceeds this %. Ignored for "
            "SAR collections (sentinel-1-grd) which carry no cloud cover."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=100),
) -> ImageryRecentResponse:
    tid = tenant_id.strip().lower()
    if not is_valid_tenant_id(tid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tid!r}",
        )
    if collection not in SUPPORTED_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported collection: {collection!r}. "
                f"Valid: {sorted(SUPPORTED_COLLECTIONS)}"
            ),
        )

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    bbox = PILOT_BBOX[tid]

    client = CopernicusClient()
    try:
        scenes = await client.search_scenes(
            bbox=bbox,
            start=start,
            end=now,
            collection=collection,
            limit=limit,
            max_cloud_cover_pct=max_cloud_cover,
        )
    except CopernicusError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Copernicus upstream error: {exc}",
        ) from exc

    return ImageryRecentResponse(
        tenant_id=tid,
        collection=collection,
        days=days,
        bbox=list(bbox),
        max_cloud_cover_pct=max_cloud_cover,
        total=len(scenes),
        scenes=[
            SceneResponse(
                scene_id=s.scene_id,
                collection=s.collection,
                captured_at=s.captured_at,
                cloud_cover_pct=s.cloud_cover_pct,
                mgrs_tile=s.mgrs_tile,
                bbox_west=s.bbox[0],
                bbox_south=s.bbox[1],
                bbox_east=s.bbox[2],
                bbox_north=s.bbox[3],
                self_href=s.self_href,
            )
            for s in scenes
        ],
    )
