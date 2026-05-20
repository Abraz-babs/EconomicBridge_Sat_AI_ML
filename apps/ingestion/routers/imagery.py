"""GET /api/v1/imagery/recent — live Sentinel scene metadata for a tenant.
POST /api/v1/imagery/download — pull one SAFE bundle to S3 (Phase A.6).

Thin router — the real work for `/recent` lives in
`services.imagery_recent` so the pass-driven sweeper (Slice 3c) can
share the same cache + fetch path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id
from services.imagery_recent import (
    SUPPORTED_COLLECTIONS,
    RecentImageryResult,
    get_recent_imagery,
)
from sources.copernicus import CopernicusError
from tasks.imagery_download import ImageryDownloadResult, download_scene_to_s3

router = APIRouter(prefix="/imagery", tags=["imagery"])


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
    fetched_at: datetime
    cached: bool
    cache_ttl_seconds: int


def _to_response(result: RecentImageryResult) -> ImageryRecentResponse:
    return ImageryRecentResponse(
        tenant_id=result.tenant_id,
        collection=result.collection,
        days=result.days,
        bbox=list(result.bbox),
        max_cloud_cover_pct=result.max_cloud_cover_pct,
        total=len(result.scenes),
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
            for s in result.scenes
        ],
        fetched_at=result.fetched_at,
        cached=result.cached,
        cache_ttl_seconds=result.cache_ttl_seconds,
    )


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

    try:
        result = await get_recent_imagery(
            tenant_id=tid,
            collection=collection,
            days=days,
            max_cloud_cover=max_cloud_cover,
            limit=limit,
        )
    except CopernicusError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Copernicus upstream error: {exc}",
        ) from exc

    return _to_response(result)


# ─── POST /imagery/download ───────────────────────────────────────────────


class ImageryDownloadRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=50)
    scene_id: str = Field(min_length=1, max_length=200)
    collection: str = "sentinel-2-l2a"
    captured_at: datetime


class ImageryDownloadResponse(BaseModel):
    download_id: UUID
    tenant_id: str
    scene_id: str
    collection: str
    status: str
    s3_bucket: str
    s3_key: str
    size_bytes: int
    sha256: str | None
    duration_ms: int
    error_message: str | None


def _to_download_response(r: ImageryDownloadResult) -> ImageryDownloadResponse:
    return ImageryDownloadResponse(
        download_id=r.download_id,
        tenant_id=r.tenant_id,
        scene_id=r.scene_id,
        collection=r.collection,
        status=r.status,
        s3_bucket=r.s3_bucket,
        s3_key=r.s3_key,
        size_bytes=r.size_bytes,
        sha256=r.sha256,
        duration_ms=r.duration_ms,
        error_message=r.error_message,
    )


@router.post(
    "/download",
    response_model=ImageryDownloadResponse,
    summary="Archive one Sentinel SAFE bundle to tenant-prefixed S3",
)
async def trigger_download(
    body: ImageryDownloadRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ImageryDownloadResponse:
    tid = body.tenant_id.strip().lower()
    if not is_valid_tenant_id(tid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tenant: {tid!r}",
        )
    if body.collection not in SUPPORTED_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported collection: {body.collection!r}. "
                f"Valid: {sorted(SUPPORTED_COLLECTIONS)}"
            ),
        )

    trace_id = getattr(request.state, "trace_id", uuid4())
    try:
        result = await download_scene_to_s3(
            session,
            tenant_id=tid,
            scene_id=body.scene_id,
            collection=body.collection,
            captured_at=body.captured_at,
            trace_id=trace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_download_response(result)
