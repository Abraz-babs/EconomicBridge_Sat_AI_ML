"""GPM IMERG half-hourly — rainfall INTENSITY and true storm timing.

WHY THIS EXISTS
---------------
The daily product (`sources/gpm_imerg.py`, GPM_3IMERGDL) accumulates over a
CALENDAR DAY in UTC. West Africa is UTC+1, and its storms are overwhelmingly
late-afternoon-to-overnight convection, so a single storm routinely straddles
00:00 UTC and is split across two daily granules — each half looking
unremarkable.

Measured on the Abuja flooding of 2026-08-30/31, which the platform missed:

    30 Aug 21:00 WAT   4.0 mm/hr
           22:30 WAT   6.3
           23:30 WAT   6.7
    31 Aug 00:30 WAT   7.4   <- peak, and 23:30 UTC on the PREVIOUS day

One continuous storm, 21:00 to 00:30 local. The daily product reported 6.5 mm
for Municipal Area Council on the 30th and 0.1 mm on the 31st, against a p99
gate of 30.6 mm. Nothing could have fired: not a threshold problem, an
aggregation problem. Lowering the gate to 5 mm would still have missed it.

The same day also exposed a spatial defect: the FCT box maximum reached ~22 mm
while the 3x3 window at the LGA centroid read 6.5 mm. The storm cell was inside
the territory but not over the points we sample.

WHAT THIS MODULE PROVIDES
-------------------------
Half-hourly precipitation RATE (mm/hr) over a region, timestamped in UTC, so a
caller can compute rolling accumulations across any window regardless of where
midnight falls, and can see peak intensity rather than a daily smear.

Rolling accumulation plus peak intensity is how operational flash-flood
guidance is actually expressed; a calendar-day total is not.

COST
----
48 granules per day per region. That is real but bounded, and it is NASA
(free, off the CDSE Processing-Unit budget). Callers should fetch a trailing
window of hours, never a season — the daily product remains the right tool for
climatology, and this one for the last day or two.

THE LATE RUN is used (`GPM_3IMERGHHL`), matching the daily feed: ~4-6 h latency
so it is operationally useful. `...HHE` (Early) is faster and noisier; the
Final run lags ~3.5 months and is for backtesting only.

HONEST LIMIT: IMERG underestimates short, intense convective cells — the exact
kind that flood a city. A 0.1 deg cell is ~11 km, so a violent storm over a few
streets is averaged across ~120 km2. Treat an intensity figure as a lower bound
on what fell, never as a measurement of what a rain gauge would have read.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from config import get_settings
from sources.gpm_imerg import (
    _FILL_BELOW,
    _lat_index,
    _lon_index,
    ImergAuthError,
    ImergError,
)

log = logging.getLogger(__name__)

_ROOT = (
    "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGHHL.07"
)
# 3B-HHR-L.MS.MRG.3IMERG.20260830-S233000-E235959.1410.V07C.HDF5
#                                                   ^^^^ minutes since midnight
_GRANULE = (
    "3B-HHR-L.MS.MRG.3IMERG.{ymd}-S{start}-E{end}.{minutes:04d}.V07{minor}.HDF5"
)
_MINORS = ("C", "B", "A")

_TIMEOUT = httpx.Timeout(120.0, connect=20.0)
_RETRYABLE = (429, 500, 502, 503, 504)
_MAX_RETRIES = 3

# Half-hourly payloads are HDF5, whose OPeNDAP ASCII labels rows POSITIONALLY
# (`precipitation[0][0], ...`). The daily product is .nc4 and labels them by
# DEGREES (`...[precipitation.lon=8.55]`). Reusing the daily parser here
# silently yields an empty grid — a 200 that looks like a dry region.
_ROW = re.compile(r"precipitation\[(\d+)\]\[(\d+)\]")


@dataclass(frozen=True)
class HalfHourGrid:
    """One 30-minute slice of rainfall RATE over a region.

    `rates` is mm/hr, not mm. Accumulation over a slice is rate / 2.
    """

    at: datetime                      # slice START, UTC
    lon0: int                         # grid index of the first lon row
    lat0: int                         # grid index of the first lat column
    rates: dict[int, list[float]]     # lon offset -> values along lat

    def peak(self) -> float:
        """Highest rate anywhere in the region, mm/hr."""
        best = 0.0
        for row in self.rates.values():
            for v in row:
                if v > _FILL_BELOW and v > best:
                    best = v
        return best

    def sample_max(self, lon: float, lat: float, *, half_width: int = 1) -> float | None:
        """Max rate in a window around a point, mm/hr.

        MAX, not mean, and that choice is the point of this module. A mean over
        a 3x3 window dilutes a convective cell across ~1,000 km2 and is how the
        Abuja storm read 6.5 mm at a centroid while the surrounding box held
        ~22 mm. For flooding, what matters is the worst cell over the place,
        not the average of it.
        """
        li0 = _lon_index(lon) - self.lon0
        lj0 = _lat_index(lat) - self.lat0
        best: float | None = None
        for li in range(li0 - half_width, li0 + half_width + 1):
            row = self.rates.get(li)
            if not row:
                continue
            for lj in range(lj0 - half_width, lj0 + half_width + 1):
                if 0 <= lj < len(row) and row[lj] > _FILL_BELOW:
                    if best is None or row[lj] > best:
                        best = row[lj]
        return best


def _parse(body: str) -> dict[int, list[float]]:
    """Positional ASCII -> {lon offset: [rates along lat]}."""
    out: dict[int, list[float]] = {}
    for raw in body.splitlines():
        label, _, rest = raw.partition(",")
        m = _ROW.search(label)
        if not m or not rest:
            continue
        lon_off = int(m.group(2))
        vals: list[float] = []
        for tok in rest.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                vals.append(float(tok))
            except ValueError:
                continue
        if vals:
            out[lon_off] = vals
    return out


def _granule_names(at: datetime) -> list[str]:
    """Candidate filenames for the slice starting at `at` (UTC)."""
    end = at + timedelta(minutes=29, seconds=59)
    minutes = at.hour * 60 + at.minute
    return [
        _GRANULE.format(
            ymd=at.strftime("%Y%m%d"),
            start=at.strftime("%H%M%S"),
            end=end.strftime("%H%M%S"),
            minutes=minutes,
            minor=minor,
        )
        for minor in _MINORS
    ]


class ImergHalfHourlyClient:
    """Reads half-hourly rainfall rate for a region."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self._settings.earthdata_token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.earthdata_token}"}

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(1, _MAX_RETRIES + 1):
            resp = await client.get(url, headers=self._headers())
            if resp.status_code not in _RETRYABLE or attempt == _MAX_RETRIES:
                return resp
            wait = min(30.0, 2.0 * attempt)
            log.warning(
                "imerg-hh %s; retrying in %.0fs (%d/%d)",
                resp.status_code, wait, attempt, _MAX_RETRIES,
            )
            await asyncio.sleep(wait)
        return resp  # pragma: no cover - loop always returns

    async def slice_grid(
        self, client: httpx.AsyncClient, *, at: datetime,
        lon0: int, lon1: int, lat0: int, lat1: int,
    ) -> HalfHourGrid | None:
        """One 30-minute region grid, or None when the granule is unpublished.

        None means "not published yet" — normal for the most recent hours, since
        the Late run trails real time. A refusal (auth, or a 5xx that outlived
        its retries) RAISES: an unpublished slice and an unreadable one must not
        collapse into the same silence, which is the same distinction the daily
        client draws.
        """
        constraint = (
            f"precipitation[0:1:0][{lon0}:1:{lon1}][{lat0}:1:{lat1}]"
        )
        doy = at.timetuple().tm_yday
        refused: int | None = None
        for name in _granule_names(at):
            url = f"{_ROOT}/{at:%Y}/{doy:03d}/{name}.ascii?{constraint}"
            resp = await self._get(client, url)
            if resp.status_code == 200:
                rates = _parse(resp.text)
                if not rates:
                    log.error(
                        "imerg-hh %s: HTTP 200 but parsed 0 rows — payload shape "
                        "changed? first 120 chars: %r", at, resp.text[:120],
                    )
                    return None
                return HalfHourGrid(at=at, lon0=lon0, lat0=lat0, rates=rates)
            if resp.status_code in (401, 403):
                raise ImergAuthError(
                    f"IMERG half-hourly {resp.status_code}: Earthdata token "
                    f"rejected. GES DISC needs 'NASA GESDISC DATA ARCHIVE' "
                    f"approved at urs.earthdata.nasa.gov."
                )
            if resp.status_code == 404:
                continue
            if resp.status_code in _RETRYABLE:
                refused = resp.status_code
                continue
            raise ImergError(f"IMERG half-hourly {resp.status_code}")
        if refused is not None:
            raise ImergError(
                f"IMERG half-hourly {refused}: no minor version of {at} "
                f"readable after {_MAX_RETRIES} retries each"
            )
        return None

    async def window(
        self, *, lon_min: float, lon_max: float, lat_min: float, lat_max: float,
        end: datetime, hours: int,
    ) -> list[HalfHourGrid]:
        """Every published slice in the `hours` ending at `end` (UTC).

        Returned oldest-first so a caller can roll a window over it directly.
        Missing slices are simply absent — the caller decides whether the
        coverage is enough to judge, exactly as the daily scan does.
        """
        if not self.configured:
            log.warning("imerg-hh: no EARTHDATA_TOKEN — skipping")
            return []

        lon0, lon1 = _lon_index(lon_min), _lon_index(lon_max)
        lat0, lat1 = _lat_index(lat_min), _lat_index(lat_max)

        # Snap to the half-hour boundary the archive publishes on.
        end = end.replace(minute=0 if end.minute < 30 else 30,
                          second=0, microsecond=0)
        slots = [end - timedelta(minutes=30 * i) for i in range(hours * 2)]

        out: list[HalfHourGrid] = []
        owns = self._http is None
        client = self._http or httpx.AsyncClient(timeout=_TIMEOUT,
                                                 follow_redirects=True)
        try:
            for at in slots:
                grid = await self.slice_grid(
                    client, at=at, lon0=lon0, lon1=lon1, lat0=lat0, lat1=lat1,
                )
                if grid is not None:
                    out.append(grid)
        finally:
            if owns:
                await client.aclose()

        out.sort(key=lambda g: g.at)
        log.info(
            "imerg-hh: %d/%d slices for the %dh ending %s",
            len(out), len(slots), hours, end.isoformat(),
        )
        return out


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def day_of(at: datetime) -> date:
    return at.date()
