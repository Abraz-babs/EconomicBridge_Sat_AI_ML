"""GET /api/v1/imagery/recent — live Sentinel scene metadata for a tenant.
POST /api/v1/imagery/download — pull one SAFE bundle to S3 (Phase A.6).

`/recent` is stateless STAC search wrapped in a 10-minute in-memory TTL
cache (Slice 3b) so the dashboard's recency indicator can poll cheaply
without hammering CDSE. `/download` is the SAFE archiver that streams
one scene from CDSE to tenant-prefixed S3 and records the catalogue row.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session, is_valid_tenant_id
from sources.copernicus import CopernicusClient, CopernicusError
from sources.nasa_firms import PILOT_BBOX
from tasks.imagery_download import ImageryDownloadResult, download_scene_to_s3

router = APIRouter(prefix="/imagery", tags=["imagery"])


# Supported STAC collections (mirrors what CDSE actually serves under
# the catalog we point at).
SUPPORTED_COLLECTIONS: frozenset[str] = frozenset(
    {"sentinel-2-l2a", "sentinel-1-grd", "sentinel-3-olci-l1b"}
)


# ─── In-memory TTL cache for /imagery/recent ──────────────────────────────
#
# CDSE STAC search is fairly expensive and the dashboard polls /recent on
# every page load. A 10-minute cache is well inside the actual scene
# cadence (Sentinel-2 = 5 days, Sentinel-1 = 6 days), so users never see
# stale data they care about, and we drop CDSE QPS by ~100x during demos.
#
# Implementation: process-local dict keyed by the public query tuple,
# guarded by an asyncio.Lock to prevent the thundering-herd-on-expiry
# pattern. No external Redis dependency — when the service scales out we
# swap this for the same Redis instance the rest of the platform uses.

_RECENT_CACHE_TTL_SECONDS: int = 600

_CacheKey = tuple[str, int, str, float | None, int]
_recent_cache: dict[_CacheKey, tuple[float, "ImageryRecentResponse"]] = {}
_recent_cache_lock = asyncio.Lock()


def _clear_recent_cache() -> None:
    """Test hook — drop everything so each test starts cold."""
    _recent_cache.clear()


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
    # Freshness metadata — used by the dashboard recency indicator.
    fetched_at: datetime
    cached: bool
    cache_ttl_seconds: int


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

    cache_key: _CacheKey = (tid, days, collection, max_cloud_cover, limit)
    now_mono = time.monotonic()

    # Fast-path: serve from cache if a fresh entry exists.
    cached = _recent_cache.get(cache_key)
    if cached is not None:
        expires_at, response = cached
        if expires_at > now_mono:
            return response.model_copy(update={"cached": True})
        # stale — fall through to refresh

    # Slow path: at most one in-flight CDSE call per cache key.
    async with _recent_cache_lock:
        # Re-check after acquiring the lock — another coroutine may have
        # refreshed while we were waiting.
        cached = _recent_cache.get(cache_key)
        now_mono = time.monotonic()
        if cached is not None and cached[0] > now_mono:
            return cached[1].model_copy(update={"cached": True})

        now_utc = datetime.now(timezone.utc)
        start = now_utc - timedelta(days=days)
        bbox = PILOT_BBOX[tid]

        client = CopernicusClient()
        try:
            scenes = await client.search_scenes(
                bbox=bbox,
                start=start,
                end=now_utc,
                collection=collection,
                limit=limit,
                max_cloud_cover_pct=max_cloud_cover,
            )
        except CopernicusError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Copernicus upstream error: {exc}",
            ) from exc

        response = ImageryRecentResponse(
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
            fetched_at=now_utc,
            cached=False,
            cache_ttl_seconds=_RECENT_CACHE_TTL_SECONDS,
        )
        _recent_cache[cache_key] = (
            time.monotonic() + _RECENT_CACHE_TTL_SECONDS,
            response,
        )
        return response


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


def _to_response(r: ImageryDownloadResult) -> ImageryDownloadResponse:
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

    return _to_response(result)
