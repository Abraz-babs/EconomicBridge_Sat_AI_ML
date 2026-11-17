"""Forecast against measured rain, LGA by LGA. Pure numpy; no I/O.

WHAT IS COMPARED
----------------
For every LGA and UTC day: the rain ECMWF forecast for that day, from the
00 UTC runs made 0 to 14 days before it, against the rain NASA's IMERG (Late
run) measured. Both sides are AREA AVERAGES over the LGA, weighted by the share
of its area each grid cell covers: 0.25 deg cells for the forecast
(processors/forecast_lga.py), 0.1 deg cells for IMERG (here), sampled on the
same lattice. A large LGA is not judged by one corner, and a small one is not
handed its neighbour's storm.

A day is WET at 1 mm or more of LGA-average rain, the rule the forecast room
uses. For each model and each lead (days before), four outcomes are counted:

    hit           forecast wet,  measured wet
    false alarm   forecast wet,  measured dry
    miss          forecast dry,  measured wet
    correct dry   forecast dry,  measured dry

The page leads with two plain numbers from them: the share of measured rain
days the forecast caught (hit rate) and the share of its rain calls that came
true (success ratio). The counts are stored, not just the ratios, so any
standard score can be recomputed from the record and every percentage carries
its sample size.

ENSEMBLE CHANCES are checked against the SHARE OF THE LGA that reached the
threshold, not a yes/no on its average. A chance averaged over the LGA's cells
is the expected share of its area that gets that rain, so the like-for-like
observation is the share that did: a Brier score with fractional observations,
against the sample's own base rate as the reference.

WHAT IT DOES NOT CLAIM
----------------------
IMERG is a satellite estimate, not a rain gauge. This measures how often two
independent estimates agree at LGA scale; it is not an accuracy against ground
truth, and nothing built on it may call it one.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from processors.forecast_lga import lattice_inside

IMERG_RES = 0.1
IMERG_LON_CELLS, IMERG_LAT_CELLS = 3600, 1800
FILL_BELOW = -9000.0       # IMERG's fill is -9999.9
# (8.60 + 180) / 0.1 is 1885.9999999999998 in binary floating point; without
# this, every exact 0.1 deg boundary lands one cell low (sources/gpm_imerg.py).
_INDEX_EPSILON = 1e-9

WET_MM = 1.0
HEAVY_MM = 10.0            # a soaking day, the forecast room's "10 mm+"
THRESHOLDS = (1, 10, 25, 50)
LEADS = 15                 # forecasts made 0..14 days before the day
CHANCE_LEADS = 10          # ensemble chances run to day 10
SHOWN_LEADS = (0, 1, 2, 3, 5, 7, 9, 14)       # the leads a reader can pick on the page
CHANCE_BINS = (0, 10, 30, 50, 70, 90, 101)     # % edges; the last bin is 90-100
CHANCE_GROUPS = ((0, 2), (3, 5), (6, 9))       # leads pooled for the chance check
MODELS = ("ifs", "aifs")


# ─── IMERG cells under an LGA ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CellWeights:
    """The IMERG cells one LGA overlaps (global indices) and each one's share of its area."""

    lon: np.ndarray
    lat: np.ndarray
    share: np.ndarray          # sums to 1

    @property
    def cells(self) -> int:
        """How many 0.1 deg cells cover the LGA."""
        return int(self.lon.size)


def imerg_index(lon: np.ndarray | float, lat: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """The containing 0.1 deg cell. Cell i spans [-180 + 0.1 i, -180 + 0.1 (i + 1)): a FLOOR."""
    li = np.floor((np.asarray(lon, dtype=np.float64) + 180.0) / IMERG_RES + _INDEX_EPSILON).astype(np.int64)
    lj = np.floor((np.asarray(lat, dtype=np.float64) + 90.0) / IMERG_RES + _INDEX_EPSILON).astype(np.int64)
    return np.clip(li, 0, IMERG_LON_CELLS - 1), np.clip(lj, 0, IMERG_LAT_CELLS - 1)


def imerg_weights(geometry: dict) -> CellWeights:
    """Share of the LGA's area in each IMERG cell it overlaps, cos(lat)-weighted."""
    xs, ys = lattice_inside(geometry)
    li, lj = imerg_index(xs, ys)
    cells, inverse = np.unique(li * IMERG_LAT_CELLS + lj, return_inverse=True)
    share = np.bincount(inverse, weights=np.cos(np.radians(ys)))
    return CellWeights(lon=cells // IMERG_LAT_CELLS, lat=cells % IMERG_LAT_CELLS, share=share / share.sum())


def box_for(bboxes: Iterable[tuple[float, float, float, float]], margin: int = 1) -> tuple[int, int, int, int]:
    """IMERG index box (lon0, lon1, lat0, lat1), inclusive, covering every outline plus a margin."""
    bs = list(bboxes)
    lon0, lat0 = imerg_index(min(b[0] for b in bs), min(b[1] for b in bs))
    lon1, lat1 = imerg_index(max(b[2] for b in bs), max(b[3] for b in bs))
    return int(lon0) - margin, int(lon1) + margin, int(lat0) - margin, int(lat1) + margin


@dataclass(frozen=True, slots=True)
class RegionArray:
    """One day of IMERG over a box: values[lon - lon0, lat - lat0] in mm; NaN = no data."""

    lon0: int
    lat0: int
    values: np.ndarray


def region_array(rows: dict[int, list[float]], box: tuple[int, int, int, int],
                 rows_lat0: int | None = None) -> RegionArray:
    """A region response (lon index -> values running north from `rows_lat0`) as an array.

    IMERG is lon-major; reading it as (lat, lon) returns rain from the wrong
    place without any error, so the axes are named in every index here.
    """
    lon0, lon1, lat0, lat1 = box
    start = lat0 if rows_lat0 is None else rows_lat0
    out = np.full((lon1 - lon0 + 1, lat1 - lat0 + 1), np.nan, dtype=np.float32)
    for li, vals in rows.items():
        i = li - lon0
        if not 0 <= i < out.shape[0]:
            continue
        v = np.asarray(vals, dtype=np.float32)
        v[v <= FILL_BELOW] = np.nan
        js = np.arange(v.size) + (start - lat0)
        keep = (js >= 0) & (js < out.shape[1])
        out[i, js[keep]] = v[keep]
    return RegionArray(lon0=lon0, lat0=lat0, values=out)


@dataclass(frozen=True, slots=True)
class Measured:
    """What IMERG measured over one LGA on one day."""

    rain_mm: float                 # area mean
    rain_max_mm: float             # wettest cell
    wet_share: dict[int, float]    # threshold mm -> share of the area at or above it
    cells: int
    coverage: float                # share of the area with valid data


def measure(w: CellWeights, arr: RegionArray) -> Measured | None:
    """The LGA's area-weighted rain for the day, or None if none of its cells has data."""
    i, j = w.lon - arr.lon0, w.lat - arr.lat0
    n_lon, n_lat = arr.values.shape
    inside = (i >= 0) & (i < n_lon) & (j >= 0) & (j < n_lat)
    v = np.full(w.share.shape, np.nan)
    v[inside] = arr.values[i[inside], j[inside]]
    ok = ~np.isnan(v)
    coverage = float(w.share[ok].sum())
    if not ok.any() or coverage <= 0.0:
        return None
    s, vals = w.share[ok] / coverage, v[ok]
    return Measured(
        rain_mm=round(float(np.sum(s * vals)), 2),
        rain_max_mm=round(float(vals.max()), 2),
        wet_share={t: round(float(np.sum(s * (vals >= t))), 3) for t in THRESHOLDS},
        cells=w.cells,
        coverage=round(coverage, 3),
    )


# ─── the record: measured days and the forecasts made for them ───────────


@dataclass(frozen=True, slots=True)
class Record:
    """Measured days and every forecast made for them, as aligned arrays.

    The day axis is the full calendar from the first measured day to the last;
    a day nobody measured is NaN, never zero (a gap is not a dry day).
    """

    lgas: list[str]
    days: list[date]
    obs: np.ndarray                  # [lga, day] mm
    share: dict[int, np.ndarray]     # threshold -> [lga, day] share of area at or above it
    rain: dict[str, np.ndarray]      # model -> [lga, day, lead] mm
    chance: dict[int, np.ndarray]    # threshold -> [lga, day, lead] %, leads 0..9


def _put(target: np.ndarray, i: int, j0: int, values: Sequence[float | None] | None, n: int) -> None:
    """Forecast element k is for day j0 + k at lead k: a diagonal of [day, lead]."""
    if not values:
        return
    xs = np.array([np.nan if v is None else v for v in values[:n]], dtype=np.float32)
    ks = np.arange(xs.size)
    js = j0 + ks
    keep = (js >= 0) & (js < target.shape[1])
    target[i, js[keep], ks[keep]] = xs[keep]


def build_record(measured: Iterable[Sequence], forecasts: Iterable[Sequence]) -> Record | None:
    """Align the two sides.

    measured:  (lga, day, rain_mm, share_1, share_10, share_25, share_50)
    forecasts: (lga, first_day, ifs, aifs, chance_1, chance_10, chance_25, chance_50),
               lists counted from first_day, None where a product was missing.
    """
    m = list(measured)
    if not m:
        return None
    lgas = sorted({r[0] for r in m})
    first, last = min(r[1] for r in m), max(r[1] for r in m)
    days = [first + timedelta(days=k) for k in range((last - first).days + 1)]
    li = {name: k for k, name in enumerate(lgas)}
    nl, nd = len(lgas), len(days)
    obs = np.full((nl, nd), np.nan, dtype=np.float32)
    share = {t: np.full((nl, nd), np.nan, dtype=np.float32) for t in THRESHOLDS}
    for lga, day, rain, *shares in m:
        i, j = li[lga], (day - first).days
        obs[i, j] = rain
        for t, s in zip(THRESHOLDS, shares, strict=True):
            share[t][i, j] = s
    rain_fc = {mdl: np.full((nl, nd, LEADS), np.nan, dtype=np.float32) for mdl in MODELS}
    chance = {t: np.full((nl, nd, CHANCE_LEADS), np.nan, dtype=np.float32) for t in THRESHOLDS}
    for lga, first_day, ifs, aifs, *chances in forecasts:
        i = li.get(lga)
        if i is None:
            continue
        j0 = (first_day - first).days
        _put(rain_fc["ifs"], i, j0, ifs, LEADS)
        _put(rain_fc["aifs"], i, j0, aifs, LEADS)
        for t, xs in zip(THRESHOLDS, chances, strict=True):
            _put(chance[t], i, j0, xs, CHANCE_LEADS)
    return Record(lgas=lgas, days=days, obs=obs, share=share, rain=rain_fc, chance=chance)


# ─── scores ───────────────────────────────────────────────────────────────


def counts(f: np.ndarray, o: np.ndarray) -> list[float]:
    """[hits, false alarms, misses, correct dry, forecast mm, measured mm,
    absolute error mm on pairs where either side was wet, those pairs,
    then hits, false alarms, misses, correct calls for SOAKING days (10 mm+)].

    The soaking-day four matter as much as the wet-day four: a model can call
    1 mm on most days and catch nearly every wet day while its rain calls are
    confirmed only half the time. Measured on Ghana, 10-16 July 2026.
    """
    valid = ~np.isnan(f) & ~np.isnan(o)
    fv, ov = f[valid], o[valid]
    fw, ow = fv >= WET_MM, ov >= WET_MM
    fh, oh = fv >= HEAVY_MM, ov >= HEAVY_MM
    wetish = fw | ow
    return [
        int(np.sum(fw & ow)), int(np.sum(fw & ~ow)), int(np.sum(~fw & ow)), int(np.sum(~fw & ~ow)),
        round(float(fv.sum()), 1), round(float(ov.sum()), 1),
        round(float(np.abs(fv - ov)[wetish].sum()), 1), int(wetish.sum()),
        int(np.sum(fh & oh)), int(np.sum(fh & ~oh)), int(np.sum(~fh & oh)), int(np.sum(~fh & ~oh)),
    ]


def scorecard(rec: Record, days: slice) -> dict[str, list[list[float]]]:
    """Per model, per lead 0..14: the counts above, over the given days."""
    return {mdl: [counts(rec.rain[mdl][:, days, k], rec.obs[:, days]) for k in range(LEADS)]
            for mdl in MODELS}


def chance_check(rec: Record) -> dict[str, dict]:
    """Per threshold: Brier score by lead [pairs, score, base-rate score] and
    calibration bins by pooled leads [pairs, sum of chances %, sum of shares]."""
    out: dict[str, dict] = {}
    for t in THRESHOLDS:
        o = rec.share[t]
        brier: list[list[float | None]] = []
        for k in range(CHANCE_LEADS):
            p = rec.chance[t][:, :, k] / 100.0
            valid = ~np.isnan(p) & ~np.isnan(o)
            if not valid.any():
                brier.append([0, None, None])
                continue
            pv, ov = p[valid], o[valid]
            base = float(ov.mean())
            brier.append([int(valid.sum()), round(float(np.mean((pv - ov) ** 2)), 5),
                          round(float(np.mean((base - ov) ** 2)), 5)])
        bins: dict[str, list[list[float]]] = {}
        for lo, hi in CHANCE_GROUPS:
            p = rec.chance[t][:, :, lo:hi + 1]
            ob = np.broadcast_to(o[:, :, None], p.shape)
            valid = ~np.isnan(p) & ~np.isnan(ob)
            pv, ov = p[valid], ob[valid]
            idx = np.digitize(pv, CHANCE_BINS[1:-1])
            bins[f"{lo}-{hi}"] = [
                [int(np.sum(idx == b)), round(float(pv[idx == b].sum()), 1), round(float(ov[idx == b].sum()), 2)]
                for b in range(len(CHANCE_BINS) - 1)
            ]
        out[str(t)] = {"brier": brier, "bins": bins}
    return out


def ribbon(rec: Record, n_days: int) -> list[dict]:
    """The most recent measured days: how many LGAs were wet, the wettest, and
    per model the four outcomes at each lead a reader can pick."""
    out: list[dict] = []
    for j in range(max(0, len(rec.days) - n_days), len(rec.days)):
        o = rec.obs[:, j]
        seen = ~np.isnan(o)
        if not seen.any():
            continue
        top = int(np.argmax(np.where(seen, o, -1.0)))
        entry: dict = {"day": rec.days[j].isoformat(), "lgas": int(seen.sum()),
                       "wet": int(np.sum(o[seen] >= WET_MM)),
                       "max_mm": round(float(o[top]), 1), "max_lga": rec.lgas[top]}
        for mdl in MODELS:
            entry[mdl] = [counts(rec.rain[mdl][:, j, k], o)[:4] for k in SHOWN_LEADS]
        out.append(entry)
    return out


def per_lga(rec: Record) -> list[dict]:
    """Each LGA's own record at the leads a reader can pick:
    [hits, false alarms, misses, correct dry, forecast mm, measured mm]."""
    out: list[dict] = []
    for i, lga in enumerate(rec.lgas):
        o = rec.obs[i]
        seen = ~np.isnan(o)
        row: dict = {"lga": lga, "days": int(seen.sum()), "wet": int(np.sum(o[seen] >= WET_MM))}
        for mdl in MODELS:
            row[mdl] = [counts(rec.rain[mdl][i, :, k], o)[:6] for k in SHOWN_LEADS]
        out.append(row)
    return out


def summarise_record(rec: Record, *, recent_days: int = 30, ribbon_days: int = 30) -> dict:
    """The stored scorecard (forecast_check_summary.summary)."""
    seen = ~np.isnan(rec.obs)
    recent_start = max(0, len(rec.days) - recent_days)
    return {
        "version": 1,
        "wet_mm": WET_MM,
        "heavy_mm": HEAVY_MM,
        "thresholds": list(THRESHOLDS),
        "leads": LEADS,
        "shown_leads": list(SHOWN_LEADS),
        "chance_bins": list(CHANCE_BINS),
        "chance_groups": [f"{lo}-{hi}" for lo, hi in CHANCE_GROUPS],
        "first_day": rec.days[0].isoformat(),
        "last_day": rec.days[-1].isoformat(),
        "days_checked": int(seen.any(axis=0).sum()),
        "lga_days": int(seen.sum()),
        "pairs": int(np.sum(~np.isnan(rec.rain["ifs"]) & seen[:, :, None])),
        "recent_days": recent_days,
        "recent_from": rec.days[recent_start].isoformat(),
        "scorecard": {"all": scorecard(rec, slice(None)), "recent": scorecard(rec, slice(recent_start, None))},
        "chances": chance_check(rec),
        "ribbon": ribbon(rec, ribbon_days),
        "lgas": per_lga(rec),
    }
