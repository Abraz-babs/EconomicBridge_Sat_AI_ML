"""Copernicus Data Space Ecosystem (CDSE) client — OAuth + STAC catalog.

This is the *metadata* layer only: we authenticate against CDSE,
search the Sentinel Hub Catalog (STAC 1.0.0) for scenes that match a
tenant ROI + date window, and return parsed `SentinelScene` records.
Actual raster download (bulk SAFE products to S3) is a separate
concern that arrives with Phase A.6.

Why CDSE (and not commercial Sentinel Hub)?
  - The operator's credentials authenticate against the CDSE OAuth
    realm; commercial Sentinel Hub rejects them with 401. CDSE is the
    Copernicus-funded successor to SciHub and is free for our usage
    tier.
  - The two systems share the STAC schema and Process API contracts
    but use different OAuth + base URLs. See ref_copernicus_endpoints.md
    for the verified URL set.

Token lifecycle:
  - Token TTL is ~1800s.
  - We cache + reuse the same token across calls and refresh
    `copernicus_token_refresh_skew_seconds` (default 60s) before the
    stated expiry.
  - One in-flight token request at a time — gated by an asyncio.Lock
    to avoid the herd of refreshes when multiple coroutines see an
    expired token simultaneously.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from config import get_settings

log = logging.getLogger(__name__)


# ─── Dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SentinelScene:
    """One STAC feature parsed into the fields we actually need."""

    scene_id: str
    collection: str
    captured_at: datetime
    bbox: tuple[float, float, float, float]
    # Cloud cover percentage (0..100). None for SAR collections.
    cloud_cover_pct: float | None
    # MGRS tile code (e.g. "31PEN") if the collection provides it.
    mgrs_tile: str | None
    # Self-href so downstream tasks know where to download from.
    self_href: str | None


class CopernicusError(RuntimeError):
    """Non-200 response, malformed body, or missing OAuth credentials."""


# ─── Token cache ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class _CachedToken:
    access_token: str
    expires_at_epoch: float  # absolute wall-clock seconds


# ─── Client ───────────────────────────────────────────────────────────────


class CopernicusClient:
    """Async client for CDSE OAuth + Sentinel Hub Catalog STAC search."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http
        self._token: _CachedToken | None = None
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.copernicus_client_id
            and self._settings.copernicus_client_secret
        )

    # ─── OAuth ─────────────────────────────────────────────────────────────

    async def access_token(self, *, now: float | None = None) -> str:
        """Return a valid bearer token, refreshing in place if needed."""
        if not self.configured:
            raise CopernicusError(
                "Copernicus credentials not configured — set "
                "COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET in .env."
            )
        wall = now if now is not None else time.time()
        skew = self._settings.copernicus_token_refresh_skew_seconds

        async with self._token_lock:
            cached = self._token
            if cached and cached.expires_at_epoch - skew > wall:
                return cached.access_token
            return (await self._refresh_token(wall=wall)).access_token

    async def _refresh_token(self, *, wall: float) -> _CachedToken:
        body = {
            "grant_type": "client_credentials",
            "client_id": self._settings.copernicus_client_id,
            "client_secret": self._settings.copernicus_client_secret,
        }
        async with self._http_ctx() as client:
            resp = await client.post(
                self._settings.copernicus_oauth_url,
                data=body,
                headers={"Accept": "application/json"},
                timeout=20.0,
            )
        if resp.status_code != 200:
            raise CopernicusError(
                f"CDSE OAuth {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise CopernicusError(
                f"CDSE OAuth: non-JSON body: {resp.text[:200]}"
            ) from exc

        access = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not access or not isinstance(expires_in, (int, float)):
            raise CopernicusError(f"CDSE OAuth: malformed body: {payload}")

        token = _CachedToken(
            access_token=str(access),
            expires_at_epoch=wall + float(expires_in),
        )
        self._token = token
        log.info(
            "copernicus.oauth refreshed — expires in %ds", int(expires_in)
        )
        return token

    # ─── STAC search ───────────────────────────────────────────────────────

    async def search_scenes(
        self,
        *,
        bbox: tuple[float, float, float, float],
        start: datetime,
        end: datetime,
        collection: str | None = None,
        limit: int = 50,
        max_cloud_cover_pct: float | None = None,
    ) -> list[SentinelScene]:
        """Run a STAC catalog search over (bbox, time window, collection).

        Args:
            bbox: (W, S, E, N) in WGS84 degrees.
            start, end: UTC datetimes bounding the search.
            collection: STAC collection id (defaults to
                settings.copernicus_default_collection).
            limit: max features to return (CDSE caps at ~100 per page).
            max_cloud_cover_pct: post-filter — drop scenes whose
                eo:cloud_cover exceeds this. None = no filter (useful
                for SAR collections which have no cloud cover).

        Returns:
            List of `SentinelScene`, sorted captured_at DESC (newest first).
        """
        if start >= end:
            raise ValueError("start must be earlier than end")
        col = collection or self._settings.copernicus_default_collection
        body = {
            "collections": [col],
            "bbox": list(bbox),
            "datetime": f"{_to_iso_utc(start)}/{_to_iso_utc(end)}",
            "limit": int(limit),
        }
        token = await self.access_token()
        async with self._http_ctx() as client:
            resp = await client.post(
                self._settings.copernicus_catalog_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    # STAC servers prefer geo+json; CDSE returns 406 on
                    # bare application/json. Accept both as fallback.
                    "Accept": "application/geo+json, application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise CopernicusError(
                f"CDSE STAC {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise CopernicusError(
                f"CDSE STAC: non-JSON body: {resp.text[:200]}"
            ) from exc

        features = payload.get("features") or []
        scenes = [_parse_feature(f, collection=col) for f in features]
        if max_cloud_cover_pct is not None:
            scenes = [
                s for s in scenes
                if s.cloud_cover_pct is None or s.cloud_cover_pct <= max_cloud_cover_pct
            ]
        scenes.sort(key=lambda s: s.captured_at, reverse=True)
        return scenes

    # ─── Scene download (OData) ────────────────────────────────────────────

    async def lookup_scene_uuid(self, scene_id: str) -> str | None:
        """Resolve a SAFE-style scene id (e.g. 'S2A_MSIL2A_...SAFE') to the
        CDSE Products UUID needed by the OData $value endpoint.

        Returns None when no product with that name is found.
        """
        token = await self.access_token()
        url = (
            f"{self._settings.copernicus_odata_url}/Products"
            f"?$filter=Name eq '{scene_id}'&$select=Id,Name&$top=1"
        )
        async with self._http_ctx() as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise CopernicusError(
                f"CDSE OData {resp.status_code}: {resp.text[:200]}"
            )
        payload = resp.json()
        rows = payload.get("value") or []
        if not rows:
            return None
        uuid = rows[0].get("Id")
        return str(uuid) if uuid else None

    def odata_download_url(self, scene_uuid: str) -> str:
        """Build the OData $value URL for a product UUID. Caller streams it."""
        return f"{self._settings.copernicus_odata_url}/Products({scene_uuid})/$value"

    async def stream_download(
        self,
        *,
        scene_uuid: str,
        timeout_seconds: int | None = None,
    ) -> httpx.Response:
        """Open a streaming GET against the OData $value URL.

        Returns an httpx.Response with `stream=True` so the caller can
        `iter_bytes()` straight into S3. Caller MUST close the response.
        We do not buffer the body in memory — SAFE bundles are huge.
        """
        token = await self.access_token()
        timeout = timeout_seconds or self._settings.copernicus_download_timeout_seconds

        # We DON'T use the borrowed/owned client wrapper here: streaming
        # responses need the underlying httpx client to outlive the call.
        # Tests pass `http=` explicitly so we route through theirs.
        client = self._http if self._http is not None else httpx.AsyncClient()
        try:
            request = client.build_request(
                "GET",
                self.odata_download_url(scene_uuid),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/octet-stream",
                },
                timeout=timeout,
            )
            resp = await client.send(request, stream=True, follow_redirects=True)
        except Exception:
            if self._http is None:
                await client.aclose()
            raise

        if resp.status_code != 200:
            body = (await resp.aread())[:200]
            await resp.aclose()
            if self._http is None:
                await client.aclose()
            raise CopernicusError(
                f"CDSE download {resp.status_code}: {body!r}"
            )
        return resp

    # ─── HTTP context ──────────────────────────────────────────────────────

    def _http_ctx(self) -> httpx.AsyncClient | _Borrowed:
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


# ─── Parsers ───────────────────────────────────────────────────────────────


def _parse_feature(feature: dict[str, Any], *, collection: str) -> SentinelScene:
    """Translate one STAC feature into a SentinelScene."""
    props = feature.get("properties") or {}
    bbox_raw = feature.get("bbox") or [0.0, 0.0, 0.0, 0.0]
    bbox: tuple[float, float, float, float] = (
        float(bbox_raw[0]),
        float(bbox_raw[1]),
        float(bbox_raw[2]),
        float(bbox_raw[3]),
    )
    self_href: str | None = None
    for link in feature.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "self":
            self_href = link.get("href")
            break
    return SentinelScene(
        scene_id=str(feature.get("id") or "<unknown>"),
        collection=collection,
        captured_at=_parse_datetime(props.get("datetime")),
        bbox=bbox,
        cloud_cover_pct=_maybe_float(props.get("eo:cloud_cover")),
        mgrs_tile=_extract_mgrs_tile(feature.get("id"), props),
        self_href=self_href,
    )


def _extract_mgrs_tile(scene_id: Any, props: dict[str, Any]) -> str | None:
    """Pull the MGRS tile code out of the scene id or properties."""
    tile = props.get("mgrs:utm_zone") or props.get("s2:mgrs_tile")
    if tile:
        return str(tile)
    # Fallback: parse from the Sentinel-2 SAFE name. Example id:
    #   S2A_MSIL2A_20260519T102601_N0512_R022_T31PEN_20260519T181155.SAFE
    # The MGRS tile is the segment that starts with "T" and is 6 chars.
    if not isinstance(scene_id, str):
        return None
    for segment in scene_id.split("_"):
        if len(segment) == 6 and segment.startswith("T") and segment[1:].isalnum():
            return segment[1:]
    return None


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    # STAC datetimes end with "Z" — fromisoformat doesn't accept that in
    # 3.10, so normalise to +00:00.
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_iso_utc(dt: datetime) -> str:
    """Render a datetime as RFC3339 Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── HTTP context wrapper ──────────────────────────────────────────────────


class _Borrowed:
    """Async-context wrapper that does NOT close the injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
