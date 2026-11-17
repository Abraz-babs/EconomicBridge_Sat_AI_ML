"""ECMWF open data — the medium-range forecast, read one field at a time.

WHAT IT READS
-------------
ECMWF publishes its operational forecasts as open data under CC BY 4.0 at
https://data.ecmwf.int/forecasts/: one GRIB2 file per run, model, stream and
step, with a JSON-lines ``.index`` beside it giving every field's byte offset
and length. We read the index and fetch only the fields we need with an HTTP
Range request (0.2-1 MB each) rather than whole files (~100 MB each).

Three products from one run:

* IFS HRES ``ifs/0p25/oper`` — the physics model, to 360 h on the 00 UTC run.
* AIFS ``aifs-single/0p25/oper`` — ECMWF's machine-learning model, same grid.
* ENS ``ifs/0p25/enfo`` (``-ep`` file) — ensemble chances of 24 h rain at or
  above 1/5/10/20/25/50/100 mm, in daily windows to 240 h.

GRID FACTS, VERIFIED ON THE LIVE FEED (2026-11-17)
--------------------------------------------------
* 1440 x 721 points at 0.25 deg. The first longitude is 180.0 (= -180) running
  east, the first latitude 90 running south. ``decode`` refuses anything else,
  because a silently shifted grid reads plausible numbers from the wrong place.
* IFS ``tp`` is in METRES, accumulated from step 0. AIFS ``tp`` is kg m-2
  (= mm), also accumulated. ``2t`` is kelvin. Chances are percent.
* The 00 UTC run was fully published by 08:01 UTC (IFS and AIFS 07:34, ENS
  chances 08:01), which is what the 09:15 UTC schedule is built around.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np

log = logging.getLogger(__name__)

BASE_URL = "https://data.ecmwf.int/forecasts"
# data.ecmwf.int keeps only the last ~4 days. ECMWF distributes the same files
# through cloud mirrors that keep the history; this is the Google Cloud one
# (the `ecmwf-opendata` package's source="google"), verified 2026-11-17 to hold
# every 00 UTC run back to April 2026 with an identical layout and index. The
# AWS mirror answered "SlowDown" to every object read that day. Used only to
# backfill the forecast check, never by the live feed.
ARCHIVE_URL = "https://storage.googleapis.com/ecmwf-open-data"
RES = 0.25
NI, NJ = 1440, 721
FIRST_LON, FIRST_LAT = 180.0, 90.0

# (model path, stream, file kind) for each product.
IFS = ("ifs", "oper", "fc")
AIFS = ("aifs-single", "oper", "fc")
ENS_CHANCES = ("ifs", "enfo", "ep")

# The last file each product writes for a 00 UTC run. A run counts as published
# only when these exist: the feed fills in step by step, and reading a half
# published run would store a forecast whose later days are silently missing.
FINAL_STEP = {IFS: 360, AIFS: 360, ENS_CHANCES: 240}

ATTEMPTS = 4
BACKOFF_S = 3.0
RETRY_STATUS = {429, 500, 502, 503, 504}


class EcmwfOpenDataError(RuntimeError):
    """The feed answered with something we cannot trust or use."""


@dataclass(frozen=True, slots=True)
class Run:
    """One forecast run, named by its base time (00 UTC only — see the task)."""

    day: date
    hour: int = 0

    @property
    def base_time(self) -> datetime:
        """The run's base time in UTC."""
        return datetime(self.day.year, self.day.month, self.day.day, self.hour, tzinfo=timezone.utc)

    def url(self, product: tuple[str, str, str], step: int, base: str = BASE_URL) -> str:
        """URL of one GRIB2 file of this run (on the live feed unless `base` says otherwise)."""
        model, stream, kind = product
        stamp = f"{self.day:%Y%m%d}{self.hour:02d}0000"
        return (f"{base}/{self.day:%Y%m%d}/{self.hour:02d}z/{model}/0p25/{stream}/"
                f"{stamp}-{step}h-{stream}-{kind}.grib2")


@dataclass(frozen=True, slots=True)
class Domain:
    """A window of the 0.25 deg grid, by inclusive row and column index.

    Columns are counted from -180 so that West Africa never wraps the
    antimeridian; rows from 90 N southward, as the file stores them.
    """

    row0: int
    row1: int
    col0: int
    col1: int

    @classmethod
    def around(cls, lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> Domain:
        """The smallest window whose cells cover the box."""
        return cls(
            row0=int(np.floor((FIRST_LAT - lat_max) / RES)),
            row1=int(np.ceil((FIRST_LAT - lat_min) / RES)),
            col0=int(np.floor((lon_min + 180.0) / RES)),
            col1=int(np.ceil((lon_max + 180.0) / RES)),
        )

    @property
    def lat0(self) -> float:
        """Centre latitude of the first (northernmost) row."""
        return FIRST_LAT - self.row0 * RES

    @property
    def lon0(self) -> float:
        """Centre longitude of the first (westernmost) column."""
        return -180.0 + self.col0 * RES

    @property
    def shape(self) -> tuple[int, int]:
        """(rows, columns)."""
        return self.row1 - self.row0 + 1, self.col1 - self.col0 + 1

    def crop(self, grid: np.ndarray) -> np.ndarray:
        """This window of a full (721, 1440) grid, as a copy."""
        return np.array(grid[self.row0:self.row1 + 1, self.col0:self.col1 + 1], dtype=np.float32)


def decode(payload: bytes) -> np.ndarray:
    """One GRIB2 message -> a (721, 1440) float array; missing points are NaN.

    eccodes is imported here, not at module load, so the rest of the ingestion
    service (and its tests) never pays for it.
    """
    import eccodes  # noqa: PLC0415 — deliberately lazy, see docstring

    gid = eccodes.codes_new_from_message(payload)
    try:
        ni, nj = eccodes.codes_get(gid, "Ni"), eccodes.codes_get(gid, "Nj")
        lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
        step = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
        if (ni, nj, float(lon0), float(lat0), float(step)) != (NI, NJ, FIRST_LON, FIRST_LAT, RES):
            raise EcmwfOpenDataError(
                f"unexpected grid {ni}x{nj} from ({lat0}, {lon0}) step {step}; refusing to read it")
        values = np.asarray(eccodes.codes_get_values(gid), dtype=np.float64)
        if eccodes.codes_get(gid, "bitmapPresent"):
            values[values == eccodes.codes_get(gid, "missingValue")] = np.nan
    finally:
        eccodes.codes_release(gid)
    return values.reshape(NJ, NI)


class EcmwfOpenDataClient:
    """Reads indexes and single fields from data.ecmwf.int, politely and with retries."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Wrap an open httpx client (the caller owns its lifetime)."""
        self._http = http

    async def _get(self, url: str, byte_range: tuple[int, int] | None = None) -> httpx.Response | None:
        """GET with retries on 429/5xx/transport errors. None means 404 (not published)."""
        headers = {"User-Agent": "EconomicBridge-ingestion/1.0"}
        if byte_range is not None:
            headers["Range"] = f"bytes={byte_range[0]}-{byte_range[0] + byte_range[1] - 1}"
        for attempt in range(1, ATTEMPTS + 1):
            try:
                resp = await self._http.get(url, headers=headers)
            except httpx.TransportError as exc:
                if attempt == ATTEMPTS:
                    raise EcmwfOpenDataError(f"{url}: {exc!r}") from exc
                await asyncio.sleep(BACKOFF_S * attempt)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code in RETRY_STATUS and attempt < ATTEMPTS:
                wait = resp.headers.get("Retry-After", "")
                await asyncio.sleep(float(wait) if wait.isdigit() else BACKOFF_S * attempt)
                continue
            if resp.status_code not in (200, 206):
                raise EcmwfOpenDataError(f"{url}: HTTP {resp.status_code}")
            return resp
        raise EcmwfOpenDataError(f"{url}: gave up after {ATTEMPTS} attempts")

    async def index(self, grib_url: str) -> list[dict] | None:
        """The parsed .index for a GRIB file, or None if it is not published."""
        resp = await self._get(grib_url.removesuffix(".grib2") + ".index")
        if resp is None:
            return None
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]

    async def fields(self, grib_url: str, want: Callable[[dict], bool]) -> list[tuple[dict, np.ndarray]]:
        """Every field of one file that `want` accepts, decoded, in index order."""
        entries = await self.index(grib_url)
        if entries is None:
            raise EcmwfOpenDataError(f"{grib_url}: not published")
        out: list[tuple[dict, np.ndarray]] = []
        for entry in entries:
            if not want(entry):
                continue
            resp = await self._get(grib_url, (int(entry["_offset"]), int(entry["_length"])))
            if resp is None or len(resp.content) != int(entry["_length"]):
                raise EcmwfOpenDataError(f"{grib_url}: short read for {entry.get('param')}")
            out.append((entry, decode(resp.content)))
        return out

    async def published(self, run: Run, product: tuple[str, str, str]) -> bool:
        """True once the product's final file for this run is on the server."""
        return await self.index(run.url(product, FINAL_STEP[product])) is not None

    async def latest_run(self, now: datetime, lookback_days: int = 2) -> tuple[Run, set[str]] | None:
        """The newest 00 UTC run whose physics model is complete, and which products it has.

        Prefers a run with all three products; falls back to the newest run with
        the physics model alone (the others are then reported as missing, never
        filled in). None if nothing in the lookback window is complete.
        """
        partial: tuple[Run, set[str]] | None = None
        for back in range(lookback_days + 1):
            run = Run((now - timedelta(days=back)).date(), 0)
            if run.base_time > now:
                continue
            have = {name for name, prod in (("ifs", IFS), ("aifs", AIFS), ("ens", ENS_CHANCES))
                    if await self.published(run, prod)}
            if have >= {"ifs", "aifs", "ens"}:
                return run, have
            if "ifs" in have and partial is None:
                partial = (run, have)
        if partial:
            log.warning("ecmwf: newest complete run lacks %s", {"aifs", "ens"} - partial[1])
        return partial
