"""GPM IMERG daily precipitation — the rainfall feed behind rainstorm warning.

ShockGuard's SAR detector only fires on a *drop* in Sentinel-1 backscatter, so
it is physically incapable of seeing a rainstorm: the hazard that took 100 roofs
off in Riyom leaves no backscatter signature of the kind a flood does. This
client supplies the missing driver — how much rain actually fell on each LGA,
each day.

What it is
----------
NASA/JAXA Global Precipitation Measurement, Integrated Multi-satellitE
Retrievals (IMERG), Level-3 daily. Product `GPM_3IMERGDL.07` — the **Late** run:
~1 day latency, which is the operationally useful one. (`...DE` Early is ~4 h
but noisier; `...DF` Final is best-quality but lags ~3.5 months — good for
back-testing a season, useless for warning anyone.)

Grid: 0.1° global, `precipitation` in **mm/day**, fill `-9999.9`.
Dimensions are **(time, lon, lat)** — lon-major. That ordering is the single
easiest thing to get wrong here; indexing it as (lat, lon) silently returns
rainfall from the wrong hemisphere rather than erroring.

Honest resolution caveat
------------------------
0.1° is ~11 km at this latitude. IMERG can say "extreme rain fell over Riyom
LGA today"; it cannot say "Tom Gangare village will lose roofs". Treat it as
LGA-level hazard warning, never as damage assessment — the damage counts in our
register come from NEMA/press for exactly this reason.

Access
------
OPeNDAP subsetting, so we pull a few hundred bytes per LGA-day instead of the
~30 MB global granule. Auth is the same Earthdata bearer token that powers the
VIIRS feed (Secrets Manager `/economicbridge/staging/earthdata/token`).

GOTCHA, verified 2026-07-26: Earthdata authorises **per application**. A token
that works against LAADS can still return 401 on GES DISC until the account
approves "NASA GESDISC DATA ARCHIVE" at urs.earthdata.nasa.gov → Applications →
Authorized Apps. The tell is metadata (`.dmr`) returning 200 while data returns
401 — that is authorisation, not a bad or expired token. `probe()` reports this
distinctly so the failure is never misread as an expiry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from config import get_settings

log = logging.getLogger(__name__)

# GES DISC OPeNDAP root for the Late-Daily v07 collection.
_OPENDAP_ROOT = (
    "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07"
)
# 3B-DAY-L.MS.MRG.3IMERG.YYYYMMDD-S000000-E235959.V07C.nc4
_GRANULE = "3B-DAY-L.MS.MRG.3IMERG.{ymd}-S000000-E235959.V07{minor}.nc4"
# The minor version letter drifts across reprocessings; try in this order.
_MINOR_VERSIONS = ("C", "B", "A")

_GRID_STEP = 0.1
_LON_CELLS = 3600
_LAT_CELLS = 1800
_FILL_BELOW = -9000.0          # sentinel is -9999.9; anything near it is no-data

# Half-width of the sampling window, in cells, around an LGA centroid. 1 → 3x3,
# i.e. ~33 km across: a convective cell can sit beside a centroid and still have
# hit the LGA, so a single cell under-reports storms.
_WINDOW = 1

_TIMEOUT = httpx.Timeout(90.0, connect=20.0)


class ImergAuthError(RuntimeError):
    """Raised when GES DISC rejects the token, with the cause disambiguated."""


class ImergError(RuntimeError):
    """Any other IMERG fetch/parse failure."""


@dataclass(frozen=True)
class DailyRain:
    """One LGA-day of rainfall, summarised over the sampling window."""

    day: date
    mean_mm: float
    max_mm: float
    cells: int

    @property
    def is_wet(self) -> bool:
        return self.max_mm > 0.0


@dataclass(frozen=True)
class RegionGrid:
    """One day's rainfall over a whole region, sampled per LGA afterwards.

    Fetching a point at a time costs one request per LGA per day — 447 LGAs x
    90 days is ~40,000 requests, which is not a feed, it is an outage. A region
    is a single request whose payload is tens of KB, so three of them (Nigeria,
    Ghana, Senegal) cover every pilot LGA for a day.
    """

    day: date
    lat0: int                         # grid index of the first lat column
    rows: dict[int, list[float]]      # lon index -> values along lat0..lat0+n

    def sample(self, lon: float, lat: float) -> DailyRain | None:
        """Window summary at a point, same 3x3 rule as the per-point path."""
        lon_i, lat_i = _lon_index(lon), _lat_index(lat)
        vals: list[float] = []
        for li in range(lon_i - _WINDOW, lon_i + _WINDOW + 1):
            row = self.rows.get(li)
            if not row:
                continue
            for lj in range(lat_i - _WINDOW, lat_i + _WINDOW + 1):
                k = lj - self.lat0
                if 0 <= k < len(row) and row[k] > _FILL_BELOW:
                    vals.append(row[k])
        if not vals:
            return None
        return DailyRain(
            day=self.day,
            mean_mm=round(sum(vals) / len(vals), 2),
            max_mm=round(max(vals), 2),
            cells=len(vals),
        )


# Cell i spans [-180 + i*0.1, -180 + (i+1)*0.1); its published centre is
# -179.95 + i*0.1. So the containing cell is a FLOOR, not a round — round()
# lands one cell (~11 km) east and produces perfectly plausible wrong numbers.
#
# The epsilon is not cosmetic: (8.60 + 180) / 0.1 evaluates to
# 1885.9999999999998 in binary floating point, so a bare int() puts an exact
# cell boundary in the cell below. Every 0.1-degree boundary is affected.
_INDEX_EPSILON = 1e-9


def _lon_index(lon: float) -> int:
    idx = int((lon + 180.0) / _GRID_STEP + _INDEX_EPSILON)
    return min(_LON_CELLS - 1, max(0, idx))


def _lat_index(lat: float) -> int:
    idx = int((lat + 90.0) / _GRID_STEP + _INDEX_EPSILON)
    return min(_LAT_CELLS - 1, max(0, idx))


def _window(idx: int, cells: int) -> tuple[int, int]:
    lo = max(0, idx - _WINDOW)
    hi = min(cells - 1, idx + _WINDOW)
    return lo, hi


def _parse_ascii(body: str) -> list[float]:
    """Pull the numeric payload out of an OPeNDAP DAP2 `.ascii` response.

    Verified against a live GES DISC response (2026-07-26) — the real shape is:

        Dataset: 3B-DAY-L.MS.MRG.3IMERG.20260602-...nc4
        precipitation.lat, 9.45, 9.55, 9.65
        precipitation.precipitation[precipitation.time=16949][precipitation.lon=8.55], 3.285, 3.45, 3.915

    Note the second line: the COORDINATE array is emitted alongside the data
    and is comma-separated exactly like it. Taking every comma-separated float
    would silently fold latitudes (~9.5) into the rainfall series as phantom
    ~9 mm readings — no error, just quietly wrong numbers.

    Data rows are distinguishable by the bracketed indices in their label;
    coordinate rows (`precipitation.lat`) have none. That is the whole rule.
    """
    values: list[float] = []
    for raw in body.splitlines():
        label, _, rest = raw.partition(",")
        if not rest or "[" not in label:
            continue                       # header, blank, or coordinate array
        for token in rest.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                continue
    return values


def _parse_region_ascii(body: str) -> dict[int, list[float]]:
    """Parse a multi-row region response into {lon_index: [values by lat]}.

    Each data row is one longitude, carrying that column's values across the
    requested latitude span, and labels its own longitude in DEGREES:

        precipitation.precipitation[...][precipitation.lon=8.55], 3.2, 3.4, ...

    Reading the degree back out of the label (rather than assuming rows arrive
    in index order) means a reordered or partial response cannot silently
    shift every LGA's rainfall onto its neighbour.
    """
    out: dict[int, list[float]] = {}
    for raw in body.splitlines():
        label, _, rest = raw.partition(",")
        if not rest or "lon=" not in label or "[" not in label:
            continue
        try:
            lon_deg = float(label.split("lon=")[1].rstrip("]").strip())
        except (IndexError, ValueError):
            continue
        vals: list[float] = []
        for token in rest.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                vals.append(float(token))
            except ValueError:
                continue
        if vals:
            out[_lon_index(lon_deg)] = vals
    return out


class GpmImergClient:
    """Reads daily rainfall for a point from GES DISC OPeNDAP."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http
        # One process-wide cache: the per-LGA sweep asks for overlapping day
        # ranges across tenants, and a granule-day is immutable once published.
        self._cache: dict[tuple[int, int, str], DailyRain | None] = {}

    @property
    def configured(self) -> bool:
        return bool(getattr(self._settings, "earthdata_token", "") or "")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.earthdata_token}",
            "Accept": "text/plain",
        }

    def _ctx(self):
        if self._http is not None:
            from sources.copernicus import _Borrowed
            return _Borrowed(self._http)
        # follow_redirects is required: GES DISC bounces through URS.
        return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    def _url(self, day: date, minor: str, lon_i: int, lat_i: int) -> str:
        lo_lon, hi_lon = _window(lon_i, _LON_CELLS)
        lo_lat, hi_lat = _window(lat_i, _LAT_CELLS)
        granule = _GRANULE.format(ymd=day.strftime("%Y%m%d"), minor=minor)
        ce = (
            f"precipitation[0][{lo_lon}:{hi_lon}][{lo_lat}:{hi_lat}]"
        )
        return (
            f"{_OPENDAP_ROOT}/{day:%Y}/{day:%m}/{granule}.ascii?{ce}"
        )

    async def daily_rain(self, lon: float, lat: float, day: date) -> DailyRain | None:
        """Rainfall over the window around (lon, lat) for `day`.

        Returns None when the granule is missing (the Late run is not published
        for the last ~24 h) or every cell is fill. Raises ImergAuthError only
        for credential problems, which callers should surface rather than
        silently treat as "no rain".
        """
        if not self.configured:
            log.debug("imerg: no EARTHDATA_TOKEN — skipping")
            return None

        lon_i, lat_i = _lon_index(lon), _lat_index(lat)
        key = (lon_i, lat_i, day.isoformat())
        if key in self._cache:
            return self._cache[key]

        body: str | None = None
        async with self._ctx() as client:
            for minor in _MINOR_VERSIONS:
                url = self._url(day, minor, lon_i, lat_i)
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 200:
                    body = resp.text
                    break
                if resp.status_code in (401, 403):
                    raise ImergAuthError(
                        "GES DISC rejected the Earthdata token "
                        f"({resp.status_code}). If the same token works against "
                        "LAADS, this is APPLICATION AUTHORISATION, not expiry: "
                        "approve 'NASA GESDISC DATA ARCHIVE' at "
                        "urs.earthdata.nasa.gov > Applications > Authorized Apps."
                    )
                if resp.status_code == 404:
                    continue      # try the next minor-version letter
                raise ImergError(f"IMERG {resp.status_code}: {resp.text[:200]}")

        if body is None:
            log.info("imerg: no granule published for %s", day)
            self._cache[key] = None
            return None

        values = [v for v in _parse_ascii(body) if v > _FILL_BELOW]
        if not values:
            self._cache[key] = None
            return None

        out = DailyRain(
            day=day,
            mean_mm=round(sum(values) / len(values), 2),
            max_mm=round(max(values), 2),
            cells=len(values),
        )
        self._cache[key] = out
        return out

    async def series(
        self, lon: float, lat: float, *, end: date, days: int,
    ) -> list[DailyRain]:
        """Consecutive daily rainfall ending at `end` (inclusive).

        Missing days are dropped rather than zero-filled — a gap in the archive
        is not a dry day, and treating it as 0 mm would drag a baseline down and
        manufacture anomalies.
        """
        out: list[DailyRain] = []
        for offset in range(days - 1, -1, -1):
            day = end - timedelta(days=offset)
            try:
                row = await self.daily_rain(lon, lat, day)
            except ImergAuthError:
                raise
            except ImergError as exc:
                log.warning("imerg: %s skipped: %s", day, exc)
                continue
            if row is not None:
                out.append(row)
        return out

    async def region_grid(
        self, *, lon0: int, lon1: int, lat0: int, lat1: int, day: date,
    ) -> RegionGrid | None:
        """One request covering a whole region for `day`.

        Index bounds are grid cells, not degrees — callers derive them from LGA
        centroids via _lon_index/_lat_index so there is one place that knows the
        grid layout.
        """
        if not self.configured:
            return None
        body: str | None = None
        async with self._ctx() as client:
            for minor in _MINOR_VERSIONS:
                granule = _GRANULE.format(ymd=day.strftime("%Y%m%d"), minor=minor)
                url = (
                    f"{_OPENDAP_ROOT}/{day:%Y}/{day:%m}/{granule}.ascii"
                    f"?precipitation[0][{lon0}:{lon1}][{lat0}:{lat1}]"
                )
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 200:
                    body = resp.text
                    break
                if resp.status_code in (401, 403):
                    raise ImergAuthError(
                        "GES DISC rejected the Earthdata token "
                        f"({resp.status_code}). If the same token works against "
                        "LAADS, this is APPLICATION AUTHORISATION, not expiry: "
                        "approve 'NASA GESDISC DATA ARCHIVE' at "
                        "urs.earthdata.nasa.gov > Applications > Authorized Apps."
                    )
                if resp.status_code == 404:
                    continue
                raise ImergError(f"IMERG {resp.status_code}: {resp.text[:200]}")

        if body is None:
            log.info("imerg: no granule published for %s", day)
            return None
        rows = _parse_region_ascii(body)
        return RegionGrid(day=day, lat0=lat0, rows=rows) if rows else None

    async def probe(self) -> tuple[bool, str]:
        """Cheap health check that distinguishes the failure modes.

        Returns (ok, message). Used by the runbook so an operator can tell
        'token expired' from 'app not authorised' without reading tracebacks.
        """
        if not self.configured:
            return False, "no EARTHDATA_TOKEN configured"
        day = date.today() - timedelta(days=2)
        try:
            row = await self.daily_rain(3.9, 11.5, day)   # Kebbi-ish point
        except ImergAuthError as exc:
            return False, str(exc)
        except ImergError as exc:
            return False, f"fetch failed: {exc}"
        if row is None:
            return True, f"authorised; no granule for {day} yet"
        return True, f"authorised; {day} max {row.max_mm} mm/day"
