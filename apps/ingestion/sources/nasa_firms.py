"""NASA FIRMS REST client.

FIRMS = Fire Information for Resource Management System. Daily fire-pixel
detections from MODIS (Terra/Aqua) and VIIRS (Suomi-NPP, NOAA-20) downscaled
to ~375 m and made available within ~3 hours of overpass.

API docs: https://firms.modaps.eosdis.nasa.gov/api/area/

Endpoint shape (CSV):
  /api/area/csv/<MAP_KEY>/<SOURCE>/<bbox>/<day_range>/<date?>

  bbox        = "W,S,E,N" in decimal degrees
  day_range   = 1..10 (days back from `date`, inclusive)
  date        = optional YYYY-MM-DD (default: today)

This client returns a list of `FirmsDetection` records — typed, parsed,
sanitised. Without a configured MAP_KEY the client falls back to deterministic
mock data so the rest of the pipeline (parser → DB writer → audit log) can be
exercised in dev without registering for an API key.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx

from config import get_settings

log = logging.getLogger(__name__)

# Default RoI bounding boxes (W, S, E, N) for the pilot tenants — mirrors
# satellite_roi in tenants.yaml. Kept here so the ingestion service has a
# self-contained config; production reads these from tenants.yaml directly.
# Bounding boxes (W, S, E, N) for every tenant that has a schema in the DB.
# Source of truth for the satellite_roi is tenants.yaml; this dict mirrors it
# so the ingestion service has a self-contained config in dev. Keep this in
# sync with the schemas created by migrations 0002 + 0008.
PILOT_BBOX: dict[str, tuple[float, float, float, float]] = {
    "kebbi":    (3.60, 10.80, 5.50, 13.20),
    "benue":    (7.70, 6.30, 10.00, 8.10),
    "plateau":  (8.30, 8.40, 10.20, 10.50),
    "kaduna":   (6.90, 9.20, 9.40, 11.60),
    "niger":    (3.50, 8.40, 7.50, 12.20),
    "zamfara":  (5.50, 11.00, 7.70, 13.40),
    "fct":      (6.70, 8.30, 8.10, 9.30),
    "nasarawa": (7.70, 7.70, 9.60, 9.30),
    "ghana":    (-3.50, 4.70, 1.20, 11.20),
    "senegal":  (-17.50, 12.30, -11.30, 15.70),
}


@dataclass(frozen=True, slots=True)
class FirmsDetection:
    """One fire-pixel detection from NASA FIRMS."""

    latitude: float
    longitude: float
    brightness_k: float | None
    bright_t31_k: float | None
    scan: float | None
    track: float | None
    detected_at: datetime
    satellite: str | None
    instrument: str | None
    confidence: str | None
    frp: float | None
    daynight: str | None
    raw: dict[str, str]


class FirmsClient:
    """Async HTTP client for NASA FIRMS area/csv endpoint."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http  # injectable for tests

    @property
    def configured(self) -> bool:
        return bool(self._settings.nasa_firms_map_key)

    async def fetch(
        self,
        *,
        bbox: tuple[float, float, float, float],
        source: str | None = None,
        day_range: int = 1,
        date: str | None = None,
    ) -> list[FirmsDetection]:
        """Return all detections inside `bbox` for the given window.

        If no MAP_KEY is configured, returns mock data anchored to the centre
        of the bbox so dev mode produces something visible.
        """
        if not self.configured:
            log.info(
                "firms: no MAP_KEY configured — returning mock data for bbox=%s",
                bbox,
            )
            return _mock_detections(bbox)

        src = source or self._settings.nasa_firms_default_source
        if not 1 <= day_range <= 5:
            raise ValueError(f"day_range must be 1..5 for NRT (got {day_range})")

        w, s, e, n = bbox
        path = (
            f"/area/csv/{self._settings.nasa_firms_map_key}"
            f"/{src}/{w},{s},{e},{n}/{day_range}"
        )
        if date:
            path = f"{path}/{date}"
        url = f"{self._settings.nasa_firms_base_url}{path}"

        # FIRMS responses are CSV. The server can return an HTML error page on
        # 4xx/5xx so we check Content-Type before parsing.
        async with self._http_ctx() as client:
            resp = await client.get(url, timeout=30.0)
        if resp.status_code != 200:
            raise FirmsError(
                f"FIRMS {resp.status_code}: {resp.text[:200]}"
            )
        ctype = resp.headers.get("content-type", "")
        if "csv" not in ctype.lower() and not resp.text.startswith("country_id,"):
            # FIRMS sometimes returns plain text without a content-type. Detect
            # by sniffing the first line.
            if "Invalid" in resp.text[:200] or "Error" in resp.text[:200]:
                raise FirmsError(f"FIRMS error body: {resp.text[:200]}")

        return list(_parse_csv(resp.text))

    # ──────────────────────────────────────────────────────────────────
    def _http_ctx(self) -> httpx.AsyncClient | _OwnedClient:
        if self._http is not None:
            # Caller-supplied client (tests / shared pool). Don't close it.
            return _Borrowed(self._http)
        return httpx.AsyncClient()


class FirmsError(RuntimeError):
    """Raised on a non-200 or malformed response from FIRMS."""


# ─── CSV parsing ───────────────────────────────────────────────────────────


def _parse_csv(text: str) -> Iterable[FirmsDetection]:
    """Parse a FIRMS CSV body into FirmsDetection records.

    FIRMS columns (as of 2026): latitude, longitude, brightness, scan, track,
    acq_date, acq_time, satellite, instrument, confidence, version, bright_t31,
    frp, daynight. Both confidence-as-percentage (MODIS) and confidence-as-text
    (VIIRS: low/nominal/high) appear in the wild — we keep the raw string.
    """
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            yield FirmsDetection(
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                # MODIS calls them brightness / bright_t31.
                # VIIRS calls them bright_ti4 / bright_ti5. Same physics,
                # different column names — accept either.
                brightness_k=_maybe_float(
                    row.get("brightness") or row.get("bright_ti4")
                ),
                bright_t31_k=_maybe_float(
                    row.get("bright_t31") or row.get("bright_ti5")
                ),
                scan=_maybe_float(row.get("scan")),
                track=_maybe_float(row.get("track")),
                detected_at=_parse_acq(row.get("acq_date"), row.get("acq_time")),
                satellite=row.get("satellite") or None,
                instrument=row.get("instrument") or None,
                confidence=row.get("confidence") or None,
                frp=_maybe_float(row.get("frp")),
                daynight=(row.get("daynight") or "").strip()[:1] or None,
                raw=dict(row),
            )
        except (KeyError, ValueError) as exc:  # pragma: no cover — defensive
            log.warning("firms: skipping malformed row: %s (%s)", row, exc)


def _maybe_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_acq(date: str | None, hhmm: str | None) -> datetime:
    """Combine FIRMS acq_date (YYYY-MM-DD) + acq_time (HHMM as int) into UTC."""
    if not date:
        return datetime.now(timezone.utc)
    y, m, d = date.split("-")
    raw = (hhmm or "0").zfill(4)
    hour, minute = int(raw[:2]), int(raw[2:])
    return datetime(int(y), int(m), int(d), hour, minute, tzinfo=timezone.utc)


# ─── Mock data for dev without MAP_KEY ─────────────────────────────────────


def _mock_detections(
    bbox: tuple[float, float, float, float],
) -> list[FirmsDetection]:
    """Return three deterministic detections inside the bbox."""
    w, s, e, n = bbox
    cx, cy = (w + e) / 2, (s + n) / 2
    qx, qy = (e - w) / 4, (n - s) / 4
    now = datetime.now(timezone.utc)
    samples = [
        (cy + qy, cx - qx, 332.4, 295.1, 18.4, "Terra",      "MODIS", "85",       "D"),
        (cy,       cx,       318.7, 291.9,  6.2, "Aqua",       "MODIS", "70",       "D"),
        (cy - qy, cx + qx, 309.5, 290.0,  2.1, "Suomi-NPP",  "VIIRS", "nominal",  "N"),
    ]
    return [
        FirmsDetection(
            latitude=lat,
            longitude=lon,
            brightness_k=bright,
            bright_t31_k=t31,
            scan=0.5,
            track=0.5,
            detected_at=now,
            satellite=sat,
            instrument=inst,
            confidence=conf,
            frp=frp,
            daynight=dn,
            raw={
                "latitude": str(lat),
                "longitude": str(lon),
                "brightness": str(bright),
                "satellite": sat,
                "instrument": inst,
                "_mock": "true",
            },
        )
        for (lat, lon, bright, t31, frp, sat, inst, conf, dn) in samples
    ]


# ─── client lifecycle helper ───────────────────────────────────────────────


class _Borrowed:
    """Async-context wrapper that does NOT close the injected client."""
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client
    async def __aexit__(self, *_exc: object) -> None:
        return None


# Sentinel — never actually instantiated, exists for type alignment above.
class _OwnedClient(httpx.AsyncClient):
    """Marker for the owned-client branch (httpx.AsyncClient itself)."""
