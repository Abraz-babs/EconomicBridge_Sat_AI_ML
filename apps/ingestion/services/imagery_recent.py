"""Cached CDSE STAC search powering /api/v1/imagery/recent.

Shared by two callers:
  * The HTTP router (`routers.imagery`) — synchronous read for the
    dashboard recency indicator.
  * The pass-driven sweeper (`tasks.pass_imagery_sweep`) — pre-warms
    the cache ~10 min after each predicted N2YO pass so the next
    dashboard load is instant.

Cache rules (CLAUDE.md §4.3 — extract magic numbers):
  * 10-minute TTL — well inside Sentinel cadence (S2: 5d, S1: 6d).
  * Key includes every public query knob so different parameter sets
    do not poison each other.
  * One in-flight refresh per key, gated by an asyncio.Lock — avoids
    the thundering-herd-on-expiry pattern.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sources.copernicus import CopernicusClient, SentinelScene
from sources.nasa_firms import PILOT_BBOX

log = logging.getLogger(__name__)


RECENT_CACHE_TTL_SECONDS: int = 600

SUPPORTED_COLLECTIONS: frozenset[str] = frozenset(
    {"sentinel-2-l2a", "sentinel-1-grd", "sentinel-3-olci-l1b"}
)


@dataclass(frozen=True, slots=True)
class RecentImageryResult:
    """Snapshot of the most-recent scenes for one (tenant, collection).

    `cached` is set by the caller when serving from cache — the stored
    record itself is always `cached=False` so a single object can be
    reused across hit/miss responses.
    """

    tenant_id: str
    collection: str
    days: int
    bbox: tuple[float, float, float, float]
    max_cloud_cover_pct: float | None
    scenes: tuple[SentinelScene, ...] = field(default_factory=tuple)
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    cached: bool = False
    cache_ttl_seconds: int = RECENT_CACHE_TTL_SECONDS


_CacheKey = tuple[str, int, str, float | None, int]
_cache: dict[_CacheKey, tuple[float, RecentImageryResult]] = {}
_cache_lock = asyncio.Lock()


def clear_cache() -> None:
    """Drop every entry. Test hook + manual operational reset."""
    _cache.clear()


async def get_recent_imagery(
    *,
    tenant_id: str,
    collection: str = "sentinel-2-l2a",
    days: int = 7,
    max_cloud_cover: float | None = None,
    limit: int = 50,
    client: CopernicusClient | None = None,
) -> RecentImageryResult:
    """Return the most-recent scenes for one (tenant, collection).

    Args mirror the query parameters of `GET /imagery/recent`. The
    `client` override exists so tests can inject an httpx MockTransport;
    production callers pass nothing and we build a fresh client.

    Raises:
        ValueError: if the tenant is not in PILOT_BBOX or the collection
            is not in SUPPORTED_COLLECTIONS.
        CopernicusError: if CDSE OAuth or STAC returns non-200 / malformed.
    """
    if tenant_id not in PILOT_BBOX:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")
    if collection not in SUPPORTED_COLLECTIONS:
        raise ValueError(
            f"Unsupported collection: {collection!r} "
            f"(valid: {sorted(SUPPORTED_COLLECTIONS)})"
        )

    cache_key: _CacheKey = (
        tenant_id, days, collection, max_cloud_cover, limit
    )

    # Fast-path: serve from cache if a fresh entry exists.
    cached = _cache.get(cache_key)
    now_mono = time.monotonic()
    if cached is not None and cached[0] > now_mono:
        return _mark_cached(cached[1])

    # Slow path: at most one in-flight CDSE call per cache key.
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached is not None and cached[0] > time.monotonic():
            return _mark_cached(cached[1])

        result = await _fetch_recent(
            tenant_id=tenant_id,
            collection=collection,
            days=days,
            max_cloud_cover=max_cloud_cover,
            limit=limit,
            client=client,
        )
        _cache[cache_key] = (
            time.monotonic() + RECENT_CACHE_TTL_SECONDS,
            result,
        )
        return result


async def _fetch_recent(
    *,
    tenant_id: str,
    collection: str,
    days: int,
    max_cloud_cover: float | None,
    limit: int,
    client: CopernicusClient | None,
) -> RecentImageryResult:
    now_utc = datetime.now(timezone.utc)
    start = now_utc - timedelta(days=days)
    bbox = PILOT_BBOX[tenant_id]

    cdse = client if client is not None else CopernicusClient()
    scenes = await cdse.search_scenes(
        bbox=bbox,
        start=start,
        end=now_utc,
        collection=collection,
        limit=limit,
        max_cloud_cover_pct=max_cloud_cover,
    )
    return RecentImageryResult(
        tenant_id=tenant_id,
        collection=collection,
        days=days,
        bbox=bbox,
        max_cloud_cover_pct=max_cloud_cover,
        scenes=tuple(scenes),
        fetched_at=now_utc,
        cached=False,
        cache_ttl_seconds=RECENT_CACHE_TTL_SECONDS,
    )


def _mark_cached(result: RecentImageryResult) -> RecentImageryResult:
    """Return a copy with `cached=True` — preserves immutability."""
    if result.cached:
        return result
    return RecentImageryResult(
        tenant_id=result.tenant_id,
        collection=result.collection,
        days=result.days,
        bbox=result.bbox,
        max_cloud_cover_pct=result.max_cloud_cover_pct,
        scenes=result.scenes,
        fetched_at=result.fetched_at,
        cached=True,
        cache_ttl_seconds=result.cache_ttl_seconds,
    )
