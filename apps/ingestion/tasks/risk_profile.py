"""Pre-season risk profile — where floods and failed rains have reached farmland, LGA by LGA.

WHY
---
An insurer pricing a season before planting (NAIC, October 2026) needs to know
where crop losses have come from: which LGAs' farmland lies where rivers flood,
which LGAs were under water when satellites last mapped a flood, and how often
the rains have failed. The platform's own feeds only begin in August 2026, so
this reads the open archives that go back decades. Operator-approved mock:
2026-10-09 (Kebbi), decisions 2026-10-10.

WHAT IS MEASURED, PER LGA
-------------------------
Flood, modelled: farmland inside the JRC/Copernicus GloFAS river flood zones
  for 1-in-10 and 1-in-100-year floods (v2.1.2, 3 arc-seconds), and how much of
  it the model floods deeper than 1 m. River floods on large rivers only.
Flood, observed: the share of the LGA, and hectares of farmland, under water in
  each UNOSAT satellite flood map (NOAA VIIRS 375 m, new water only), with how
  much of the LGA cloud hid in that window. Nigeria only for now.
Seasonal rainfall (CHIRPS v3 monthly, 1991 to the last complete season): the
  season is the months that averaged >= 50 mm in 1991-2020; normal is the
  1991-2020 median season total; a drought season falls below 80% of normal.
Failed rains (CHIRPS v3 daily, IMERG-distributed, 1998 onward), on the
  LGA-average daily rainfall:
  * onset (Sivakumar 1988, as AGRHYMET uses it): the first day, from the 1st of
    the season's first month, on which three days bring >= 20 mm with no dry
    spell longer than 7 days in the next 30;
  * false start: such a rain before the onset that IS followed by a longer dry
    spell — the rain farmers plant on, then lose;
  * long dry spell: 10 or more days under 1 mm in the 30-90 days after onset,
    when cereals flower and fill grain;
  * late onset: 20 or more days after the LGA's median onset, or none by the
    end of the season's third month.
Exposure: farmland (ESA WorldCover 2021 cropland), villages, people and children
  under five (village_light, Nigerian pilots), and the cited disaster register.

BANDS — one published rule for every state, so a High means the same everywhere
  flood    High: >= 10% of farmland in the 1-in-10-year zone, or >= 5% of the LGA
           under water in a mapped flood. Moderate: >= 3% of farmland in the
           1-in-100-year zone, or >= 1% under water. Otherwise Low.
  drought  High: a season below 80% of normal at least 1 year in 5.
           Moderate: at least 1 year in 10. Otherwise Low.
  rains    (failed rains) see dryspell_band.

Rows go to tenant_<id>.lga_risk_profile and tenant_<id>.risk_overlay (migration
0061), keyed by the last complete season; next year's run adds a new round
beside this one. Yearly and manual:

    python -m scripts.run_risk_profile --tenant kebbi
"""
from __future__ import annotations

import json
import logging
import math
import os
import struct
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

import numpy as np
from sqlalchemy import text

from db import get_session_factory, set_tenant_schema
from sources import lga_boundaries as lb

log = logging.getLogger(__name__)

METHOD = "risk_profile_v1"

# ── sources ───────────────────────────────────────────────────────────────
CHIRPS_MONTHLY = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/africa/tifs/chirps-v3.0.{y}.{m:02d}.tif"
CHIRPS_DAILY = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/sat/{y}/"
                "chirps-v3.0.sat.{y}.{m:02d}.{d:02d}.tif")
JRC_HAZARD = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/"
              "RP{rp}/ID{tid}_{name}_RP{rp}_depth_reclass.tif")
WORLDCOVER = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
# JRC numbers its 10-degree tiles; these are the ones over our pilots (read off
# the RP10 directory listing, 2026-10-10). A new country adds its tiles here.
JRC_TILE_IDS = {"N30_W20": 103, "N20_W20": 104, "N20_W10": 110, "N10_W10": 111,
                "N20_W0": 117, "N10_W0": 118, "N20_E10": 125, "N10_E10": 126}


@dataclass(frozen=True)
class FloodMap:
    key: str            # stored key, e.g. "2024-09"
    label: str          # as the page prints it
    url: str
    flood_layer: str    # exact layer names: one archive can hold several windows
    cloud_layer: str


UNOSAT_MAPS: dict[str, tuple[FloodMap, ...]] = {
    "NG": (
        FloodMap("2024-09", "5–9 Sep 2024", "https://unosat.org/static/unosat_filesystem/3963/FL20240902NGA_SHP.zip",
                 "VIIRS_20240905_20240909_MaximumFloodExtent_NGA", "VIIRS_20240905_20240909_CloudObstruction_NGA"),
        FloodMap("2022-10", "13–17 Oct 2022", "https://unosat.org/static/unosat_filesystem/3418/FL20221019NGA_SHP.zip",
                 "VIIRS_20221013_20221017_MaximumFloodWaterExtent_Nigeria",
                 "VIIRS_20221013_20221017_CloudObstruction_Nigeria"),
    ),
}
COUNTRY = {"ghana": "GH", "senegal": "SN"}          # every other pilot is Nigerian

SOURCES = ("CHIRPS v3.0 monthly and daily (UCSB Climate Hazards Center, CC BY 4.0); "
           "JRC/Copernicus GloFAS flood hazard maps v2.1.2 (© European Union, CC BY 4.0); "
           "ESA WorldCover 2021 v200 (CC BY 4.0); UNOSAT VIIRS flood extents; "
           "GRID3 villages with Meta/CIESIN HRSL population (CC BY 4.0)")

# ── the rules ─────────────────────────────────────────────────────────────
FIRST_YEAR = 1991
NORMAL = (1991, 2020)
DAILY_FIRST_YEAR = 1998            # IMERG-distributed daily CHIRPS starts here
WET_MONTH_MM = 50.0
DROUGHT_FRACTION = 0.80
SEASON_MONTHS = tuple(range(3, 12))  # March..November are read; the season is chosen per LGA
DAILY_FROM, DAILY_TO = (3, 1), (10, 31)
DRY_DAY_MM = 1.0
ONSET_RAIN_MM = 20.0
ONSET_SPAN_DAYS = 3
ONSET_CHECK_DAYS = 30
ONSET_MAX_DRY = 7
MID_FROM, MID_TO = 30, 90
LONG_DRY_DAYS = 10
LATE_ONSET_DAYS = 20

FLOOD_HIGH_RP10, FLOOD_MOD_RP100 = 10.0, 3.0      # % of farmland in the zone
MAPPED_HIGH, MAPPED_MOD = 5.0, 1.0                # % of the LGA under water
DROUGHT_HIGH, DROUGHT_MOD = 1 / 5, 1 / 10         # share of seasons below 80%
RAINS_HIGH, RAINS_MOD = 1 / 3, 1 / 5              # share of seasons with failed rains

RES = 1 / 1200.0                  # analysis grid = the JRC grid, 3 arc-seconds
OVERLAY_STEP = 3                  # overlays at 9 arc-seconds
CROPLAND = 40                     # ESA WorldCover class


# ─── pure rules (unit-tested) ─────────────────────────────────────────────

def season_stats(monthly: dict[tuple[int, int], float], years: list[int]) -> dict:
    """Season months, normal, totals and drought seasons from monthly LGA rainfall."""
    normal_years = [y for y in years if NORMAL[0] <= y <= NORMAL[1]]
    clim = {m: float(np.mean([monthly[(y, m)] for y in normal_years if (y, m) in monthly] or [0.0]))
            for m in SEASON_MONTHS}
    season = [m for m in SEASON_MONTHS if clim[m] >= WET_MONTH_MM]
    totals = {y: round(sum(monthly.get((y, m), 0.0) for m in season), 1) for y in years}
    normal = median(totals[y] for y in normal_years) if normal_years else 0.0
    dry = [y for y in years if normal and totals[y] < DROUGHT_FRACTION * normal]
    worst = min(years, key=lambda y: totals[y])
    vals = np.array([totals[y] for y in years])
    return {
        "season_months": season,
        "monthly_normal_mm": {str(m): round(clim[m], 1) for m in SEASON_MONTHS},
        "normal_mm": round(normal, 1),
        "cv_pct": round(100 * float(vals.std() / vals.mean()), 1) if vals.mean() else None,
        "totals": {str(y): totals[y] for y in years},
        "drought_seasons": dry,
        "worst": {"year": worst, "pct_of_normal": round(100 * totals[worst] / normal, 1) if normal else None},
        "first_year": years[0], "last_year": years[-1],
    }


def longest_dry_run(rain: np.ndarray, lo: int, hi: int) -> int:
    """Longest run of days under DRY_DAY_MM in rain[lo:hi]."""
    best = run = 0
    for v in rain[max(lo, 0):max(hi, 0)]:
        run = run + 1 if v < DRY_DAY_MM else 0
        best = max(best, run)
    return best


def find_onset(rain: np.ndarray, start: int, last: int) -> tuple[int | None, bool]:
    """(onset index, false start before it) for one season of daily LGA rainfall.

    rain[i] is mm on day i of the daily window; the search runs from `start` to
    `last` inclusive. A day qualifies when it is wet and it and the next two
    days bring >= ONSET_RAIN_MM; it is the onset when no dry spell longer than
    ONSET_MAX_DRY follows in the next ONSET_CHECK_DAYS, otherwise it is a false
    start and the search goes on.
    """
    false_start = False
    n = len(rain)
    for d in range(start, min(last, n - ONSET_SPAN_DAYS) + 1):
        if rain[d] < DRY_DAY_MM or float(rain[d:d + ONSET_SPAN_DAYS].sum()) < ONSET_RAIN_MM:
            continue
        if longest_dry_run(rain, d + 1, d + 1 + ONSET_CHECK_DAYS) <= ONSET_MAX_DRY:
            return d, false_start
        false_start = True
    return None, false_start


def failed_rains(daily: dict[int, np.ndarray], window_start: date, season_months: list[int]) -> dict:
    """Onset, false starts, late onsets and long dry spells for one LGA, per year.

    daily[year] is the LGA-average rainfall from window_start's month/day of that
    year; a year with any missing day is left out rather than guessed.
    """
    if not season_months:
        return {"years": [], "onsets": {}}
    first_m = season_months[0]
    third_m = season_months[min(2, len(season_months) - 1)]
    last_m = season_months[-1]
    onsets: dict[int, int | None] = {}
    false_starts, long_dry, longest = [], [], {}
    years = sorted(y for y, r in daily.items() if not np.isnan(r).any())
    for y in years:
        r = daily[y]
        w0 = date(y, window_start.month, window_start.day)
        start = (date(y, first_m, 1) - w0).days
        last = (_month_end(y, third_m) - w0).days
        end_of_season = (_month_end(y, last_m) - w0).days
        onset, fs = find_onset(r, start, last)
        onsets[y] = onset
        if fs:
            false_starts.append(y)
        if onset is not None:
            mid = longest_dry_run(r, onset + MID_FROM, min(onset + MID_TO, end_of_season + 1, len(r)))
            longest[str(y)] = mid
            if mid >= LONG_DRY_DAYS:
                long_dry.append(y)
    seen = [d for d in onsets.values() if d is not None]
    med = median(seen) if seen else None
    late = [y for y, d in onsets.items() if d is None or (med is not None and d - med >= LATE_ONSET_DAYS)]
    any_failed = sorted(set(false_starts) | set(late) | set(long_dry))

    def as_date(y: int, d: int | None) -> str | None:
        return None if d is None else (date(y, window_start.month, window_start.day) + timedelta(days=d)).isoformat()

    return {
        "years": years,
        "onsets": {str(y): as_date(y, d) for y, d in onsets.items()},
        "onset_median": as_date(2001, round(med))[5:] if med is not None else None,   # "MM-DD"
        "false_starts": false_starts,
        "late_onsets": late,
        "long_dry_spells": long_dry,
        "longest_mid_dry": longest,
        "failed_seasons": any_failed,
    }


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def flood_band(rp10_crop_pct: float | None, rp100_crop_pct: float | None, mapped_max_pct: float | None) -> str:
    if rp10_crop_pct is None and rp100_crop_pct is None and mapped_max_pct is None:
        return "none"
    rp10, rp100, m = rp10_crop_pct or 0.0, rp100_crop_pct or 0.0, mapped_max_pct or 0.0
    if rp10 >= FLOOD_HIGH_RP10 or m >= MAPPED_HIGH:
        return "high"
    if rp100 >= FLOOD_MOD_RP100 or m >= MAPPED_MOD:
        return "moderate"
    return "low"


def share_band(count: int, seasons: int, high: float, moderate: float) -> str:
    if seasons <= 0:
        return "none"
    share = count / seasons
    if share >= high - 1e-9:
        return "high"
    return "moderate" if share >= moderate - 1e-9 else "low"


def drought_band(dry_seasons: int, seasons: int) -> str:
    return share_band(dry_seasons, seasons, DROUGHT_HIGH, DROUGHT_MOD)


def dryspell_band(failed_seasons: int, seasons: int) -> str:
    """Failed rains — a false start, a late onset or a long dry spell after onset."""
    return share_band(failed_seasons, seasons, RAINS_HIGH, RAINS_MOD)


def jrc_tile_names(bbox: tuple[float, float, float, float]) -> list[str]:
    """JRC 10-degree hazard tiles (named by top latitude, left longitude) over a box."""
    names = []
    for top in range((math.floor(bbox[1] / 10) + 1) * 10, (math.floor(bbox[3] / 10) + 1) * 10 + 1, 10):
        for left in range(math.floor(bbox[0] / 10) * 10, math.floor(bbox[2] / 10) * 10 + 1, 10):
            ns = f"N{top}" if top > 0 else f"S{-top}"
            names.append(f"{ns}_{'W' if left <= 0 else 'E'}{abs(left)}")
    return names


def worldcover_tile_names(bbox: tuple[float, float, float, float]) -> list[str]:
    """ESA WorldCover 3-degree tiles (named by lower-left corner) over a box."""
    out = []
    for lat in range(math.floor(bbox[1] / 3) * 3, math.floor(bbox[3] / 3) * 3 + 1, 3):
        for lon in range(math.floor(bbox[0] / 3) * 3, math.floor(bbox[2] / 3) * 3 + 1, 3):
            out.append(f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
    return out


def png_gray(arr: np.ndarray) -> bytes:
    """An 8-bit greyscale PNG of a 2-D uint8 array (no image library needed)."""
    h, w = arr.shape
    raw = b"".join(b"\x00" + np.ascontiguousarray(arr[i], dtype=np.uint8).tobytes() for i in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pct(part: float, whole: float, nd: int = 1) -> float | None:
    return round(100.0 * float(part) / float(whole), nd) if whole else None


def _rdp(pts: list, eps: float) -> list:
    """Douglas-Peucker on an open polyline."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return _rdp(pts[: idx + 1], eps)[:-1] + _rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def simplify_geometry(geometry: dict, tol: float = 0.004, nd: int = 4) -> dict:
    """A light outline for maps and the PDF: rings simplified to `tol` degrees.

    A closed ring has identical ends, so it is split at its farthest vertex
    first; rings that collapse below a triangle are dropped (tiny islands).
    """
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            pts = [(float(p[0]), float(p[1])) for p in ring]
            if len(pts) < 4:
                continue
            far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
            s = _rdp(pts[: far + 1], tol)[:-1] + _rdp(pts[far:], tol)
            if len(s) >= 4:
                rings.append([[round(x, nd), round(y, nd)] for x, y in s])
        if rings:
            out.append(rings)
    if not out:
        return geometry
    return {"type": "Polygon", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiPolygon", "coordinates": out}


# ─── reading the archives ─────────────────────────────────────────────────

def _gdal_env() -> None:
    # No CPL_VSIL_CURL_ALLOWED_EXTENSIONS: it would refuse the query-string retry
    # path; EMPTY_DIR already stops GDAL probing for sidecar files. No HEAD
    # request either: one request fewer per file on a server that rate-limits.
    for k, v in {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_USE_HEAD": "NO",
                 "GDAL_HTTP_MAX_RETRY": "4", "GDAL_HTTP_RETRY_DELAY": "3"}.items():
        os.environ.setdefault(k, v)


class _Pace:
    """At most `per_second` file opens per second across all threads.

    The Climate Hazards Center server refuses an address that reads too much
    too fast (HTTP 403 for minutes). Measured 2026-10-10 from eu-west-1: about
    1.5 monthly files a second (~1.3 MB/s) was accepted; 3.5 daily files a
    second (~4.5 MB/s) was refused within a minute. So the archive is read at a
    steady, polite rate, and a refusal pauses EVERY reader for a cool-down and
    slows the pace by a third — never a burst of retries."""

    def __init__(self, per_second: float, floor: float = 0.25) -> None:
        import threading

        self.gap = 1.0 / per_second
        self.max_gap = 1.0 / floor
        self.next = 0.0
        self.last_block = float("-inf")
        self.lock = threading.Lock()

    def set_rate(self, per_second: float) -> None:
        with self.lock:
            self.gap = 1.0 / per_second

    def rate(self) -> float:
        return 1.0 / self.gap

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        if at > now:
            time.sleep(at - now)

    def blocked(self, cool_down: float = 300.0) -> bool:
        """Every reader waits out the cool-down; the first report of a block
        also slows the pace. True for that first report."""
        with self.lock:
            now = time.monotonic()
            first = now - self.last_block > cool_down
            if first:
                self.gap = min(self.gap * 1.5, self.max_gap)
            self.last_block = now
            self.next = max(self.next, now + cool_down)
        return first


_PACE = _Pace(1.0)
MONTHLY_RATE, DAILY_RATE = 1.5, 1.0     # files a second; the daily archive (~6,900 files) takes about 2 hours


@dataclass
class Zones:
    """Every requested LGA labelled on a 0.05-degree rainfall grid."""
    keys: list[tuple[str, str]]                       # (tenant, lga), label = index + 1
    labels: np.ndarray | None = None
    fallback: dict[int, int] = field(default_factory=dict)  # label -> flat cell for LGAs smaller than a cell


def _zones_for(lgas: list, transform, shape) -> Zones:
    from rasterio.features import rasterize
    from rasterio.transform import rowcol

    z = Zones(keys=[(b.tenant, b.lga) for b in lgas])
    z.labels = rasterize([(b.geometry, i + 1) for i, b in enumerate(lgas)], out_shape=shape,
                         transform=transform, fill=0, dtype="int32")
    present = np.bincount(z.labels.ravel(), minlength=len(lgas) + 1)
    for i, b in enumerate(lgas):
        if present[i + 1] == 0:                       # a district smaller than one cell
            cx, cy = lb.centroid(b.geometry)
            r, c = rowcol(transform, cx, cy)
            r, c = min(max(r, 0), shape[0] - 1), min(max(c, 0), shape[1] - 1)
            z.fallback[i + 1] = int(r * shape[1] + c)
    return z


def _zone_means(z: Zones, arr: np.ndarray, nodata) -> np.ndarray:
    """Mean of valid cells per LGA (index = label); NaN where an LGA has none."""
    valid = np.isfinite(arr) & (arr > -1) & ((arr != nodata) if nodata is not None else True)
    lab = np.where(valid, z.labels, 0).ravel()
    n = len(z.keys) + 1
    sums = np.bincount(lab, weights=np.where(valid, arr, 0.0).ravel(), minlength=n)
    cnt = np.bincount(lab, minlength=n)
    out = np.where(cnt > 0, sums / np.maximum(cnt, 1), np.nan)
    flat, vflat = arr.ravel(), valid.ravel()
    for label, cell in z.fallback.items():
        out[label] = float(flat[cell]) if vflat[cell] else np.nan
    return out


def _vsi(url: str, attempt: int = 0) -> str:
    """The /vsicurl path for one attempt. Odd attempts add a query string the
    server ignores, so GDAL treats them as a new file and cannot reuse a header
    it cached cut short (seen 2026-10-10 with CHC under load). Even attempts use
    the plain path. (The '/vsicurl?url=' options form is not accepted by the
    GDAL in our image.)"""
    return "/vsicurl/" + url + (f"?try={attempt}" if attempt % 2 else "")


def _read_window(url: str, bounds: tuple[float, float, float, float], tries: int = 6):
    import rasterio
    from rasterio.windows import from_bounds

    last: Exception | None = None
    for attempt in range(tries):
        _PACE.wait()
        try:
            with rasterio.open(_vsi(url, attempt)) as src:
                if src.crs is None or src.transform.is_identity:
                    raise RuntimeError(f"{url}: opened without georeferencing (header cut short)")
                win = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
                return src.read(1, window=win).astype("float64"), src.window_transform(win), src.nodata
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "403" in str(exc) or "429" in str(exc):
                if _PACE.blocked():
                    log.warning("rainfall archive refusing (%s on %s): every reader pauses 5 minutes, "
                                "then reads at %.2f files/s", str(exc)[:40], url.rsplit("/", 1)[-1], _PACE.rate())
                continue                      # wait() holds this reader until the cool-down ends
            if attempt:
                log.warning("rainfall archive: %s attempt %d failed (%s)", url.rsplit("/", 1)[-1], attempt + 1,
                            str(exc)[:120])
            time.sleep(5 * (attempt + 1))
    raise last if last else RuntimeError(f"{url}: unreadable")


def read_monthly(lgas: list, bounds, years: list[int], workers: int = 4) -> dict[tuple[str, str], dict]:
    """(tenant, lga) -> {(year, month): mm} from CHIRPS v3 monthly."""
    _gdal_env()
    _PACE.set_rate(MONTHLY_RATE)
    jobs = [(y, m) for y in years for m in SEASON_MONTHS]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda ym: (ym, _read_window(CHIRPS_MONTHLY.format(y=ym[0], m=ym[1]), bounds)), jobs))
    (_, (a0, t0, _)) = res[0]
    z = _zones_for(lgas, t0, a0.shape)
    out: dict[tuple[str, str], dict] = {k: {} for k in z.keys}
    for (y, m), (arr, tr, nodata) in res:
        if arr.shape != a0.shape or tr != t0:
            raise RuntimeError(f"CHIRPS monthly grid changed at {y}-{m:02d}")
        means = _zone_means(z, arr, nodata)
        for i, k in enumerate(z.keys):
            if np.isfinite(means[i + 1]):
                out[k][(y, m)] = float(means[i + 1])
    return out


def read_daily(lgas: list, bounds, years: list[int], workers: int = 4) -> tuple[dict, date]:
    """(tenant, lga) -> {year: daily mm array from 1 March to 31 October}.

    A day that cannot be read after every retry stays NaN, and failed_rains
    leaves that year out rather than guess; the count of such days is logged.
    """
    _gdal_env()
    _PACE.set_rate(DAILY_RATE)
    start = date(2001, *DAILY_FROM)
    span = (date(2001, *DAILY_TO) - start).days + 1
    days = [(y, date(y, *DAILY_FROM) + timedelta(days=i)) for y in years for i in range(span)]
    z: Zones | None = None
    grid: dict = {}
    out: dict = {}

    def one(item, tries=6):
        y, d = item
        try:
            return item, _read_window(CHIRPS_DAILY.format(y=d.year, m=d.month, d=d.day), bounds, tries=tries)
        except Exception as exc:  # noqa: BLE001
            log.warning("daily rainfall %s unreadable: %r", d, exc)
            return item, None

    def take(y: int, d: date, got) -> None:
        nonlocal z, out
        arr, tr, nodata = got
        if z is None:
            z = _zones_for(lgas, tr, arr.shape)
            grid["t"], grid["s"] = tr, arr.shape
            out = {key: {yy: np.full(span, np.nan) for yy in years} for key in z.keys}
        if arr.shape != grid["s"] or tr != grid["t"]:
            raise RuntimeError(f"CHIRPS daily grid changed at {d}")
        means = _zone_means(z, arr, nodata)
        i = (d - date(y, *DAILY_FROM)).days
        for j, key in enumerate(z.keys):
            out[key][y][i] = means[j + 1]

    failed = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, (item, got) in enumerate(ex.map(one, days)):
            if got is None:
                failed.append(item)
            else:
                take(*item, got)
            if k and k % 500 == 0:
                log.info("daily rainfall: %d/%d days read (%.0fs)", k, len(days), time.time() - t0)
    for item in list(failed):                # one slow, single-threaded second pass
        _, got = one(item, tries=8)
        if got is not None:
            take(*item, got)
            failed.remove(item)
    if z is None:
        raise RuntimeError("no daily rainfall file could be read")
    if failed:
        log.warning("daily rainfall: %d days unreadable; their years are left out: %s",
                    len(failed), sorted({y for y, _ in failed}))
    return out, start


def _download(url: str, path: str) -> str | None:
    import httpx

    for attempt in range(4):
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            return path
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return None


@dataclass
class Grid:
    """One tenant's 3-arc-second analysis grid."""
    bounds: tuple[float, float, float, float]       # padded
    raw: tuple[float, float, float, float]          # the LGAs' own box
    transform: object
    shape: tuple[int, int]
    labels: np.ndarray
    pix_km2: np.ndarray                             # per row
    n: int
    _w: np.ndarray | None = None

    def km2(self, mask: np.ndarray | None = None) -> np.ndarray:
        """Area in km² per LGA (index = label), optionally only where mask is set."""
        if self._w is None:
            self._w = np.repeat(self.pix_km2[:, None], self.shape[1], axis=1).ravel()
        lab = self.labels if mask is None else np.where(mask, self.labels, 0)
        return np.bincount(lab.ravel(), weights=self._w, minlength=self.n + 1)


def tenant_grid(lgas: list) -> Grid:
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    raw = (min(b.bbox[0] for b in lgas), min(b.bbox[1] for b in lgas),
           max(b.bbox[2] for b in lgas), max(b.bbox[3] for b in lgas))
    bounds = (raw[0] - 0.05, raw[1] - 0.05, raw[2] + 0.05, raw[3] + 0.05)
    tr = from_origin(bounds[0], bounds[3], RES, RES)
    shape = (int(round((bounds[3] - bounds[1]) / RES)), int(round((bounds[2] - bounds[0]) / RES)))
    labels = rasterize([(b.geometry, i + 1) for i, b in enumerate(lgas)], out_shape=shape,
                       transform=tr, fill=0, dtype="int16")
    lat = bounds[3] - (np.arange(shape[0]) + 0.5) * RES
    pix = ((RES * 110.6) * (RES * 111.32) * np.cos(np.radians(lat))).astype("float32")
    return Grid(bounds, raw, tr, shape, labels, pix, len(lgas))


def flood_zones(g: Grid, cache_dir: str) -> dict[str, np.ndarray]:
    """rp10 / rp100 (any depth) and rp100_deep (> 1 m) masks on the tenant grid."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    depth = {rp: np.zeros(g.shape, dtype="uint8") for rp in (10, 100)}
    for name in jrc_tile_names(g.bounds):
        tid = JRC_TILE_IDS.get(name)
        if tid is None:
            raise RuntimeError(f"JRC tile {name} is not in JRC_TILE_IDS — add it from the RP10 listing")
        for rp in (10, 100):
            path = os.path.join(cache_dir, f"jrc_{name}_rp{rp}.tif")
            if not os.path.exists(path) and _download(JRC_HAZARD.format(rp=rp, tid=tid, name=name), path) is None:
                continue
            part = np.zeros(g.shape, dtype="uint8")
            with rasterio.open(path) as src:
                reproject(rasterio.band(src, 1), part, dst_transform=g.transform, dst_crs="EPSG:4326",
                          resampling=Resampling.nearest)
            ok = (part >= 1) & (part <= 4)
            depth[rp] = np.where(ok & (part > depth[rp]), part, depth[rp])
    return {"rp10": (depth[10] >= 1) & (depth[10] <= 4), "rp100": (depth[100] >= 1) & (depth[100] <= 4),
            "rp100_deep": (depth[100] >= 2) & (depth[100] <= 4)}


def cropland(g: Grid) -> np.ndarray:
    """ESA WorldCover 2021 cropland on the tenant grid (read at ~100 m, nearest)."""
    import rasterio
    from rasterio import Affine
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds

    _gdal_env()
    crop = np.zeros(g.shape, dtype=bool)
    for tile in worldcover_tile_names(g.bounds):
        try:
            with rasterio.open("/vsicurl/" + WORLDCOVER.format(tile=tile)) as src:
                west, south, east, north = src.bounds
                ib = (max(west, g.bounds[0]), max(south, g.bounds[1]),
                      min(east, g.bounds[2]), min(north, g.bounds[3]))
                if ib[0] >= ib[2] or ib[1] >= ib[3]:
                    continue
                win = from_bounds(*ib, src.transform).round_offsets().round_lengths()
                oh, ow = max(1, int(win.height // 10)), max(1, int(win.width // 10))
                arr = src.read(1, window=win, out_shape=(oh, ow), resampling=Resampling.nearest)
                atr = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
                part = np.zeros(g.shape, dtype="uint8")
                reproject(arr, part, src_transform=atr, src_crs="EPSG:4326", dst_transform=g.transform,
                          dst_crs="EPSG:4326", resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
                crop |= part == CROPLAND
        except Exception as exc:  # noqa: BLE001  (ocean tiles do not exist)
            if "404" in str(exc) or "does not exist" in str(exc) or "No such file" in str(exc):
                continue
            raise
    return crop


def _rings_mask(g: Grid, shp_path: str) -> np.ndarray:
    """Polygons of a shapefile burned onto the grid by ring parity: every ring adds
    one, odd counts are inside, so holes cancel and ring order never matters."""
    import shapefile
    from rasterio.enums import MergeAlg
    from rasterio.features import rasterize

    b = g.bounds
    rings = []
    for s in shapefile.Reader(shp_path).iterShapes():
        pts = np.asarray(s.points, dtype="float64")
        parts = list(s.parts) + [len(pts)]
        for a, z in zip(parts[:-1], parts[1:]):
            ring = pts[a:z]
            if (len(ring) < 4 or ring[:, 0].max() < b[0] or ring[:, 0].min() > b[2]
                    or ring[:, 1].max() < b[1] or ring[:, 1].min() > b[3]):
                continue
            rings.append({"type": "Polygon", "coordinates": [ring.tolist()]})
    if not rings:
        return np.zeros(g.shape, dtype=bool)
    acc = rasterize(((r, 1) for r in rings), out_shape=g.shape, transform=g.transform,
                    dtype="uint16", merge_alg=MergeAlg.add)
    return (acc % 2) == 1


def mapped_floods(g: Grid, maps: tuple[FloodMap, ...], cache_dir: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """event key -> (flood water mask, cloud mask)."""
    out = {}
    for fm in maps:
        zpath = os.path.join(cache_dir, f"unosat_{fm.key}.zip")
        if not os.path.exists(zpath):
            _download(fm.url, zpath)
        folder = os.path.join(cache_dir, f"unosat_{fm.key}")
        if not os.path.isdir(folder):
            zipfile.ZipFile(zpath).extractall(folder)
        found = {f[:-4]: os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs if f.endswith(".shp")}
        out[fm.key] = (_rings_mask(g, found[fm.flood_layer]), _rings_mask(g, found[fm.cloud_layer]))
    return out


def overlay_png(g: Grid, mask: np.ndarray) -> tuple[bytes, list[float], int, int]:
    """A mask cut to the LGAs' own box, inside the state only, at OVERLAY_STEP."""
    c0 = int(round((g.raw[0] - g.bounds[0]) / RES))
    r0 = int(round((g.bounds[3] - g.raw[3]) / RES))
    c1 = int(round((g.raw[2] - g.bounds[0]) / RES))
    r1 = int(round((g.bounds[3] - g.raw[1]) / RES))
    k = OVERLAY_STEP
    h, w = (r1 - r0) // k, (c1 - c0) // k
    inside = g.labels[r0:r0 + h * k, c0:c0 + w * k] > 0
    sub = mask[r0:r0 + h * k, c0:c0 + w * k] & inside
    img = (sub.reshape(h, k, w, k).max(axis=(1, 3)) * 255).astype("uint8")
    west, north = g.bounds[0] + c0 * RES, g.bounds[3] - r0 * RES
    return png_gray(img), [west, north - h * k * RES, west + w * k * RES, north], w, h


# ─── platform data ────────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


async def _exposure(tenant: str, names: list[str]) -> tuple[dict[str, dict], dict[str, list]]:
    """Villages/people/under-5 (latest village_light round) and the cited register, by LGA."""
    key = {_norm(n): n for n in names}
    expo: dict[str, dict] = {}
    reg: dict[str, list] = {}
    async with get_session_factory()() as s:
        await set_tenant_schema(s, tenant)
        if (await s.execute(text("SELECT to_regclass('village_light') IS NOT NULL"))).scalar():
            rows = (await s.execute(text(
                "SELECT lga, count(*), COALESCE(sum(people), 0), COALESCE(sum(under5), 0) FROM village_light "
                "WHERE period = (SELECT max(period) FROM village_light) GROUP BY lga"))).all()
            for lga, villages, people, under5 in rows:
                if key.get(_norm(lga)):
                    expo[key[_norm(lga)]] = {"villages": int(villages), "people": int(people), "under5": int(under5)}
        if (await s.execute(text("SELECT to_regclass('shock_events') IS NOT NULL"))).scalar():
            rows = (await s.execute(text(
                "SELECT lga, event_type, zone_name, metrics FROM shock_events WHERE source = 'historical_v1'"))).all()
            for lga, kind, name, metrics in rows:
                m = metrics if isinstance(metrics, dict) else json.loads(metrics or "{}")
                if key.get(_norm(lga)):
                    reg.setdefault(key[_norm(lga)], []).append({"type": kind, "date": m.get("event_date"), "name": name})
    for v in reg.values():
        v.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    return expo, reg


PROFILE_UPSERT = text("""
    INSERT INTO lga_risk_profile (lga, through_season, method, band_flood, band_drought, band_rains, figures, sources)
    VALUES (:lga, :through, :method, :band_flood, :band_drought, :band_rains, CAST(:figures AS JSONB), :sources)
    ON CONFLICT (lga, through_season, method) DO UPDATE SET
        band_flood = EXCLUDED.band_flood, band_drought = EXCLUDED.band_drought, band_rains = EXCLUDED.band_rains,
        figures = EXCLUDED.figures, sources = EXCLUDED.sources, measured_at = NOW()
    WHERE (lga_risk_profile.band_flood, lga_risk_profile.band_drought, lga_risk_profile.band_rains,
           lga_risk_profile.figures)
      IS DISTINCT FROM (EXCLUDED.band_flood, EXCLUDED.band_drought, EXCLUDED.band_rains, EXCLUDED.figures)
""")

OVERLAY_UPSERT = text("""
    INSERT INTO risk_overlay (through_season, method, layer, label, west, south, east, north, width, height, png)
    VALUES (:through, :method, :layer, :label, :west, :south, :east, :north, :width, :height, :png)
    ON CONFLICT (through_season, method, layer) DO UPDATE SET
        label = EXCLUDED.label, west = EXCLUDED.west, south = EXCLUDED.south, east = EXCLUDED.east,
        north = EXCLUDED.north, width = EXCLUDED.width, height = EXCLUDED.height, png = EXCLUDED.png,
        measured_at = NOW()
    WHERE risk_overlay.png IS DISTINCT FROM EXCLUDED.png
""")


# ─── the run ──────────────────────────────────────────────────────────────

def _union_box(lgas: list, pad: float = 0.1) -> tuple[float, float, float, float]:
    return (min(b.bbox[0] for b in lgas) - pad, min(b.bbox[1] for b in lgas) - pad,
            max(b.bbox[2] for b in lgas) + pad, max(b.bbox[3] for b in lgas) + pad)


async def run_risk_profile(tenants: list[str], *, through: int, write: bool = True,
                           daily: bool = True, cache_dir: str = "/tmp/risk_profile",
                           collect: dict | None = None) -> dict[str, str]:
    """Measure every requested tenant's LGAs through the given season and store the round.

    `collect`, when given, receives each tenant's rows and overlays (for a dry
    run to be reviewed before anything is written).
    """
    os.makedirs(cache_dir, exist_ok=True)
    by_tenant = {t: list(lb.for_tenant(t)) for t in tenants}
    missing = [t for t, v in by_tenant.items() if not v]
    if missing:
        raise RuntimeError(f"no LGA boundaries for {missing}")
    all_lgas = [b for t in tenants for b in by_tenant[t]]
    box = _union_box(all_lgas)
    years = list(range(FIRST_YEAR, through + 1))
    t0 = time.time()
    monthly = read_monthly(all_lgas, box, years)
    log.info("risk profile: monthly rainfall for %d LGAs, %d seasons (%.0fs)", len(all_lgas), len(years), time.time() - t0)
    rains: dict = {}
    if daily:
        t1 = time.time()
        rains, start = read_daily(all_lgas, box, list(range(DAILY_FIRST_YEAR, through + 1)))
        log.info("risk profile: daily rainfall read (%.0fs)", time.time() - t1)

    out: dict[str, str] = {}
    for t in tenants:
        lgas = by_tenant[t]
        names = [b.lga for b in lgas]
        g = tenant_grid(lgas)
        a_all = g.km2()
        crop = cropland(g)
        a_crop = g.km2(crop)
        zones = flood_zones(g, cache_dir)
        za = {k: g.km2(v) for k, v in zones.items()}
        zc = {k: g.km2(v & crop) for k, v in zones.items()}
        maps = UNOSAT_MAPS.get(COUNTRY.get(t, "NG"), ())
        mapped = mapped_floods(g, maps, cache_dir) if maps else {}
        m_stats = {k: (g.km2(w), g.km2(w & crop), g.km2(c)) for k, (w, c) in mapped.items()}
        expo, reg = await _exposure(t, names)

        rows = []
        bands = {"flood": {}, "drought": {}, "rains": {}}
        for i, b in enumerate(lgas):
            A, C = float(a_all[i + 1]), float(a_crop[i + 1])
            flood = {
                "rp10_crop_pct": pct(zc["rp10"][i + 1], C), "rp10_crop_ha": round(float(zc["rp10"][i + 1]) * 100),
                "rp100_crop_pct": pct(zc["rp100"][i + 1], C), "rp100_crop_ha": round(float(zc["rp100"][i + 1]) * 100),
                "rp100_deep_crop_pct": pct(zc["rp100_deep"][i + 1], C),
                "rp10_area_pct": pct(za["rp10"][i + 1], A), "rp100_area_pct": pct(za["rp100"][i + 1], A),
                "mapped": {fm.key: {"label": fm.label,
                                    "area_pct": pct(m_stats[fm.key][0][i + 1], A, 2),
                                    "crop_pct": pct(m_stats[fm.key][1][i + 1], C, 2),
                                    "crop_ha": round(float(m_stats[fm.key][1][i + 1]) * 100),
                                    "cloud_pct": pct(m_stats[fm.key][2][i + 1], A)} for fm in maps},
            }
            mapped_max = max([v["area_pct"] or 0.0 for v in flood["mapped"].values()], default=None)
            rain = season_stats(monthly[(t, b.lga)], years)
            figures = {
                "area_km2": round(A, 1), "cropland_ha": round(C * 100), "cropland_pct": pct(C, A),
                "flood": flood, "rain": rain,
                "exposure": expo.get(b.lga), "register": reg.get(b.lga, []),
                "centroid": [round(c, 5) for c in lb.centroid(b.geometry)],
                "outline": simplify_geometry(b.geometry),
            }
            band_rains = "none"
            if daily:
                fr = failed_rains(rains[(t, b.lga)], start, rain["season_months"])
                figures["rains"] = fr
                band_rains = dryspell_band(len(fr["failed_seasons"]), len(fr["years"]))
            band_flood = flood_band(flood["rp10_crop_pct"], flood["rp100_crop_pct"], mapped_max)
            band_drought = drought_band(len(rain["drought_seasons"]), len(years))
            for k, v in (("flood", band_flood), ("drought", band_drought), ("rains", band_rains)):
                bands[k][v] = bands[k].get(v, 0) + 1
            rows.append({"lga": b.lga, "through": through, "method": METHOD, "band_flood": band_flood,
                         "band_drought": band_drought, "band_rains": band_rains,
                         "figures": json.dumps(figures, separators=(",", ":")), "sources": SOURCES})

        overlays = []
        layers = [("rp10_farmland", "Farmland in the 1-in-10-year flood zone", zones["rp10"] & crop)]
        layers += [(f"flood_{fm.key}", f"Flood water seen {fm.label}", mapped[fm.key][0]) for fm in maps]
        for layer, label, mask in layers:
            png, (w_, s_, e_, n_), w, h = overlay_png(g, mask)
            overlays.append({"through": through, "method": METHOD, "layer": layer, "label": label,
                             "west": w_, "south": s_, "east": e_, "north": n_, "width": w, "height": h, "png": png})

        summary = (f"{len(rows)} LGAs · flood {bands['flood']} · drought {bands['drought']} · "
                   f"failed rains {bands['rains']} · farmland {round(float(a_crop.sum()) * 100):,} ha")
        if write:
            async with get_session_factory()() as s:
                await set_tenant_schema(s, t)
                await s.execute(PROFILE_UPSERT, rows)
                await s.execute(OVERLAY_UPSERT, overlays)
                await s.commit()
        if collect is not None:
            collect[t] = {"rows": rows, "overlays": overlays}
        out[t] = summary
        log.info("risk profile %s: %s", t, summary)
    return out
