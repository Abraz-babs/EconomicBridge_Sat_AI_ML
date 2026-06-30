"""NASA VIIRS Black Marble catalog client (LAADS DAAC).

VIIRS Black Marble = daily night-light radiance composite from the Suomi-NPP
satellite, downscaled to ~500 m and lunar-BRDF corrected so we get a clean
"how-bright-is-this-pixel-tonight" signal. Dim clusters of inhabited land
correlate strongly with under-electrified, often poor settlements — the
core signal Module 01 (Economic Visibility) uses for poverty mapping.

This client is the **catalog/metadata** layer only: given a tenant ROI bbox
and a date window, we ask LAADS DAAC which VNP46A2/A4 granules cover the
area and return parsed `BlackMarbleGranule` records. Actual raster
sampling (pixel-level radiance reads off the COG) lands in a Phase B
slice that adds rasterio + a streaming S3 reader; the same processor
pipeline that consumes our catalog records here will consume the raster
samples then.

Auth: NASA Earthdata Bearer token (urs.earthdata.nasa.gov → Generate
Token). Empty token means "no API call" — the catalog returns an empty
list and the processor falls back to seed_v1 rows. We never hit the
real LAADS endpoint without an explicit token because the rate limits
are tight (~50 req/min per token).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlackMarbleGranule:
    """One VNP46* granule that covers (part of) a tenant ROI."""

    granule_id: str             # e.g. "VNP46A2.A2026140.h18v07.001.2026141..."
    product: str                # "VNP46A2" or "VNP46A4"
    captured_at: datetime       # UTC midpoint of the granule's day
    tile_h: int                 # MODIS sinusoidal horizontal index
    tile_v: int                 # MODIS sinusoidal vertical index
    download_url: str           # https://ladsweb... .h5 (auth required)
    size_bytes: int | None      # may be missing from the catalog response


class BlackMarbleError(RuntimeError):
    """Non-200 response, malformed body, or missing Earthdata token."""


class BlackMarbleClient:
    """Async LAADS DAAC catalog client for VIIRS Black Marble.

    The LAADS DAAC catalog exposes a JSON listing endpoint:
        /archive/allData/{COLLECTION}/{PRODUCT}/{YYYY}/{DDD}/.json

    Response shape (LAADS v2):
        {
            "content": [
                {"name": "VNP46A2.A2026100.h00v01.002.20260108.h5",
                 "downloadsLink": "...", "size": 4181490, ...},
                ...
            ],
            "file_count": 540, ...
        }

    A granule's name encodes the date (A{YYYY}{DDD}), tile (h{HH}v{VV}),
    and processing collection. We filter to granules whose MODIS sinusoidal
    tile intersects the requested bbox before returning to the caller.
    """

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self._settings.earthdata_token)

    async def search_granules(
        self,
        *,
        bbox: tuple[float, float, float, float],
        date: datetime,
        product: str | None = None,
        max_results: int = 20,
    ) -> list[BlackMarbleGranule]:
        """List Black Marble granules that intersect `bbox` on `date`.

        Args:
            bbox: (W, S, E, N) in WGS84 degrees.
            date: UTC date of interest (we use date.date() to build the
                day-of-year path).
            product: VNP46A2 (daily) or VNP46A4 (annual). Defaults to
                settings.viirs_black_marble_product.
            max_results: cap on returned granules.

        Returns:
            List of granules whose tile bbox intersects `bbox`. Empty when
            no token is configured (so the caller can fall back to seed_v1
            rows without raising). The list is unsorted; callers typically
            pick the lowest tile_h+tile_v that fits the centroid.
        """
        if not self.configured:
            log.debug("viirs.black_marble: no Earthdata token — empty result")
            return []

        prod = product or self._settings.viirs_black_marble_product
        collection = self._settings.earthdata_laads_collection
        yyyy = date.year
        ddd = date.timetuple().tm_yday
        # Trailing-slash-before-.json is required: LAADS treats the path
        # as a directory listing and .json is the response-format suffix.
        url = (
            f"{self._settings.earthdata_laads_base_url}"
            f"/archive/allData/{collection}/{prod}/{yyyy}/{ddd:03d}/.json"
        )

        async with self._http_ctx() as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {self._settings.earthdata_token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        if resp.status_code == 404:
            # Day not yet ingested by LAADS (typically next-day latency).
            return []
        if resp.status_code != 200:
            raise BlackMarbleError(
                f"LAADS DAAC {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BlackMarbleError(
                f"LAADS DAAC: non-JSON body: {resp.text[:200]}"
            ) from exc

        rows = payload if isinstance(payload, list) else payload.get("content") or []
        granules = [_parse_granule(r, product=prod) for r in rows]
        granules = [g for g in granules if g is not None]
        kept = [
            g for g in granules
            if _tile_intersects_bbox(g.tile_h, g.tile_v, bbox)
        ]
        return kept[:max_results]

    def _http_ctx(self) -> httpx.AsyncClient | _Borrowed:
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


# ─── Parsers ──────────────────────────────────────────────────────────────


def _parse_granule(row: Any, *, product: str) -> BlackMarbleGranule | None:
    if not isinstance(row, dict):
        return None
    name = row.get("name") or row.get("fileName") or row.get("Name")
    if not isinstance(name, str) or product not in name:
        return None
    parts = name.split(".")
    if len(parts) < 5:
        return None
    try:
        ayyyyddd = parts[1]
        captured_at = _parse_julian(ayyyyddd)
        tile = parts[2]
        tile_h = int(tile[1:3])
        tile_v = int(tile[4:6])
    except (ValueError, IndexError):
        return None

    size_raw = row.get("size") or row.get("fileSize") or row.get("Size")
    size_bytes: int | None
    try:
        size_bytes = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_bytes = None

    href = (
        row.get("downloadsLink")
        or row.get("downloadUrl")
        or row.get("url")
        or ""
    )
    return BlackMarbleGranule(
        granule_id=name,
        product=product,
        captured_at=captured_at,
        tile_h=tile_h,
        tile_v=tile_v,
        download_url=str(href),
        size_bytes=size_bytes,
    )


def _parse_julian(ayyyyddd: str) -> datetime:
    """Parse 'A{YYYY}{DDD}' (e.g. 'A2026140') into a UTC midnight datetime."""
    if not ayyyyddd.startswith("A") or len(ayyyyddd) != 8:
        raise ValueError(f"bad julian: {ayyyyddd!r}")
    year = int(ayyyyddd[1:5])
    doy = int(ayyyyddd[5:8])
    if not (1 <= doy <= 366):
        raise ValueError(f"bad day-of-year: {doy}")
    from datetime import timedelta
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)


# ─── Tile geometry ────────────────────────────────────────────────────────


def _tile_intersects_bbox(
    h: int, v: int, bbox: tuple[float, float, float, float],
) -> bool:
    """Approximate MODIS sinusoidal tile vs. WGS84 bbox intersection.

    MODIS sinusoidal: 36 columns (h 0..35) × 18 rows (v 0..17), each tile
    1200×1200 km. We invert h/v to approximate WGS84 lon/lat ranges and
    test intersection. This is *good enough* for ROI gating; production
    raster sampling will use exact reprojection.
    """
    tile_lon_west, tile_lon_east, tile_lat_south, tile_lat_north = \
        _approx_tile_bbox(h, v)
    bw, bs, be, bn = bbox
    return not (
        tile_lon_east < bw or tile_lon_west > be
        or tile_lat_north < bs or tile_lat_south > bn
    )


def _approx_tile_bbox(h: int, v: int) -> tuple[float, float, float, float]:
    """WGS84 bbox of a Black Marble tile (lon_w, lon_e, lat_s, lat_n).

    VNP46A2 is on a GEOGRAPHIC (Plate Carrée) 10°×10° tile grid — NOT the MODIS
    sinusoidal grid. h00 starts at lon −180 (east-positive), v00 at lat +90
    (south-positive), each tile exactly 10°. (Verified against a live granule:
    Nigeria sits in h18/h19 × v07/v08. The previous sinusoidal math here never
    intersected Nigeria, which is why poverty fell back to the proxy.)
    """
    lon_w = -180.0 + h * 10.0
    lon_e = lon_w + 10.0
    lat_n = 90.0 - v * 10.0
    lat_s = lat_n - 10.0
    return lon_w, lon_e, lat_s, lat_n


# ─── HTTP context wrapper ─────────────────────────────────────────────────


class _Borrowed:
    """Async-context wrapper that does NOT close the injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
