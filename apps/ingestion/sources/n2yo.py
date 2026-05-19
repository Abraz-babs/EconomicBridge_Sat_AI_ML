"""N2YO REST client — live satellite-pass tracking.

N2YO (https://www.n2yo.com) is a public satellite-tracking service that
exposes a REST API for orbital queries. We use the `radiopasses` endpoint
because it returns overhead passes filtered by minimum elevation —
exactly what we need to time Sentinel / MODIS / VIIRS ingestion.

Endpoint shape:
    GET /rest/v1/satellite/radiopasses/{satid}/{lat}/{lng}/{alt}/{days}/{min_el}/&apiKey=...

  satid   = NORAD catalog ID (e.g. 39634 = SENTINEL 1A)
  alt     = observer altitude (metres). We always pass 0 (sea-level
            equivalent is close enough for satellites at 700+ km).
  days    = number of days to look ahead (1..10).
  min_el  = minimum peak elevation in degrees (1..90).

The response includes one `info` block + a list of `passes`. We parse
each pass into a `SatellitePass` dataclass — typed UTC timestamps and
explicit field names so downstream code never has to think in seconds-
since-epoch or N2YO's column names.

This module is HTTP-only — no DB, no clock, no env outside settings.
The scheduler in `tasks.passes_refresh` (Phase A.4) will wrap this.

API quota: free tier = 1000 transactions per hour. One transaction per
call regardless of how many passes are returned. We rate-limit at the
caller level (see TODO in routers.passes).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import get_settings

log = logging.getLogger(__name__)

# ─── Satellite catalogue ───────────────────────────────────────────────────
#
# NORAD IDs sourced from https://www.n2yo.com (cross-checked with the
# Copernicus / NASA mission pages). Add new sats here when we extend
# beyond fire + SAR/optical EO.
#
# Each entry: (norad_id, group). `group` is the canonical pipeline label
# the caller uses to pick the right downstream ingestion task.

SATELLITE_CATALOG: dict[str, tuple[int, str]] = {
    # Copernicus Sentinel — SAR (radar, all-weather)
    "SENTINEL-1A":  (39634, "S1"),
    "SENTINEL-1C":  (60989, "S1"),
    # Copernicus Sentinel — Optical (MSI)
    "SENTINEL-2A":  (40697, "S2"),
    "SENTINEL-2B":  (42063, "S2"),
    # NASA EO satellites carrying VIIRS (heat/fire signatures)
    "SUOMI-NPP":    (37849, "VIIRS"),
    "NOAA-20":      (43013, "VIIRS"),
    # NASA EO satellites carrying MODIS
    "TERRA":        (25994, "MODIS"),
    "AQUA":         (27424, "MODIS"),
}


# ─── Dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SatellitePass:
    """One overhead pass of a satellite over an observer point."""

    satellite_name: str       # canonical key from SATELLITE_CATALOG
    satellite_group: str      # S1 | S2 | VIIRS | MODIS
    norad_id: int
    observer_lat: float
    observer_lon: float
    # All three timestamps are UTC.
    start_utc: datetime
    max_utc: datetime
    end_utc: datetime
    # Degrees. Max elevation is the most useful for imagery quality.
    start_elevation_deg: float
    max_elevation_deg: float
    end_elevation_deg: float
    # Azimuth at the peak (compass bearing the satellite is in at maxEl).
    max_azimuth_deg: float
    max_azimuth_compass: str  # "N" | "NE" | "E" | ...
    duration_seconds: int


class N2yoError(RuntimeError):
    """Raised on a non-200 or malformed response from N2YO."""


# ─── Client ────────────────────────────────────────────────────────────────


class N2yoClient:
    """Async HTTP client for the N2YO radiopasses endpoint."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self._settings.n2yo_api_key)

    async def fetch_passes(
        self,
        *,
        satellite_key: str,
        observer_lat: float,
        observer_lon: float,
        days: int = 2,
        min_elevation: int | None = None,
    ) -> list[SatellitePass]:
        """Return the next overhead passes for one satellite over one point.

        Args:
            satellite_key: Key into SATELLITE_CATALOG (e.g. "SENTINEL-1A").
            observer_lat, observer_lon: WGS84 of the observation point.
            days: 1..10. N2YO caps at 10.
            min_elevation: 1..90. Defaults to settings.n2yo_default_min_elevation.

        Returns:
            A list of SatellitePass (possibly empty). Empty is *valid*:
            it just means no qualifying pass in the window.
        """
        if not self.configured:
            raise N2yoError(
                "N2YO_API_KEY is not configured — set it in .env "
                "(no mock mode for satellite passes; mocks would lie about "
                "when imagery will arrive)."
            )
        if satellite_key not in SATELLITE_CATALOG:
            raise ValueError(f"Unknown satellite: {satellite_key!r}")
        if not 1 <= days <= 10:
            raise ValueError(f"days must be 1..10 (got {days})")

        norad_id, group = SATELLITE_CATALOG[satellite_key]
        # `... or default` would silently coerce 0 to default — that hides
        # the bug instead of surfacing it. Use explicit None check.
        min_el = (
            self._settings.n2yo_default_min_elevation
            if min_elevation is None
            else min_elevation
        )
        if not 1 <= min_el <= 90:
            raise ValueError(f"min_elevation must be 1..90 (got {min_el})")

        url = (
            f"{self._settings.n2yo_base_url}"
            f"/radiopasses/{norad_id}"
            f"/{observer_lat}/{observer_lon}/0/{days}/{min_el}"
            f"/&apiKey={self._settings.n2yo_api_key}"
        )

        async with self._http_ctx() as client:
            resp = await client.get(url, timeout=30.0)
        if resp.status_code != 200:
            raise N2yoError(f"N2YO {resp.status_code}: {resp.text[:200]}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise N2yoError(f"N2YO: non-JSON body: {resp.text[:200]}") from exc

        if "error" in payload:
            raise N2yoError(f"N2YO error: {payload['error']}")

        passes_raw = payload.get("passes") or []
        return [
            _parse_pass(
                row,
                satellite_key=satellite_key,
                satellite_group=group,
                norad_id=norad_id,
                observer_lat=observer_lat,
                observer_lon=observer_lon,
            )
            for row in passes_raw
        ]

    def _http_ctx(self) -> httpx.AsyncClient | _Borrowed:
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


# ─── Parsing helpers ───────────────────────────────────────────────────────


def _parse_pass(
    row: dict,
    *,
    satellite_key: str,
    satellite_group: str,
    norad_id: int,
    observer_lat: float,
    observer_lon: float,
) -> SatellitePass:
    start_epoch = int(row["startUTC"])
    end_epoch = int(row["endUTC"])
    # N2YO's `radiopasses` endpoint omits the `duration` field (only
    # `visualpasses` includes it). Derive from the timestamps so callers
    # always get the real pass length.
    duration = int(row.get("duration") or 0) or (end_epoch - start_epoch)
    return SatellitePass(
        satellite_name=satellite_key,
        satellite_group=satellite_group,
        norad_id=norad_id,
        observer_lat=observer_lat,
        observer_lon=observer_lon,
        start_utc=_utc_from_epoch(start_epoch),
        max_utc=_utc_from_epoch(row["maxUTC"]),
        end_utc=_utc_from_epoch(end_epoch),
        start_elevation_deg=float(row.get("startEl", 0.0)),
        max_elevation_deg=float(row.get("maxEl", 0.0)),
        end_elevation_deg=float(row.get("endEl", 0.0)),
        max_azimuth_deg=float(row.get("maxAz", 0.0)),
        max_azimuth_compass=str(row.get("maxAzCompass", "")),
        duration_seconds=duration,
    )


def _utc_from_epoch(seconds: int | float) -> datetime:
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc)


# ─── client lifecycle helper ──────────────────────────────────────────────


class _Borrowed:
    """Async-context wrapper that does NOT close the injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
