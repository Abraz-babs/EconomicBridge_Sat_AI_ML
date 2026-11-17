"""ECMWF grid -> one forecast per LGA. Pure numpy; no I/O.

AREA WEIGHTS, NOT A CENTROID LOOKUP
-----------------------------------
A 0.25 deg cell is about 28 km across; many LGAs are smaller than that and most
straddle several cells. Reading the cell under the centroid would give a small
LGA the whole of a neighbour's storm, and a large one the value of a single
corner. So each LGA's value is the average of the cells it overlaps, weighted
by how much of the LGA falls in each one.

Overlap is measured by sampling the outline on a 0.025 deg lattice (about
2.8 km, a hundred samples per cell) with an even-odd ray cast — the same test
sources/lga_boundaries.py uses, vectorised. The production image carries no
geometry library, and this does not need one. The lattice is global, so the
same LGA always gets the same weights.

The wettest overlapping cell is kept beside the average: an LGA-wide mean of
4 mm can hide one corner forecast at 15 mm, and a reader should see both.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sources.ecmwf_opendata import RES, Domain

SUB_STEP = 0.025


@dataclass(frozen=True, slots=True)
class Weights:
    """The domain cells one LGA overlaps, and each cell's share of its area."""

    rows: np.ndarray
    cols: np.ndarray
    share: np.ndarray        # sums to 1

    @property
    def cells(self) -> int:
        """How many forecast cells cover this LGA."""
        return int(self.rows.size)


@dataclass(frozen=True, slots=True)
class ForecastFields:
    """One run, cropped to the domain and turned into daily fields.

    Any product may be missing; a missing product stays None all the way to
    the reader and is never filled in from another one.
    """

    rain_ifs: list[np.ndarray]                       # mm per UTC day, days 0..14
    rain_aifs: list[np.ndarray] | None               # mm per UTC day
    chances: dict[int, list[np.ndarray]] | None      # threshold mm -> % per day, days 0..9
    temp_dawn: list[np.ndarray] | None               # deg C at 06 UTC, days 0..5
    temp_afternoon: list[np.ndarray] | None          # deg C at 15 UTC, days 0..5


@dataclass(frozen=True, slots=True)
class LgaForecast:
    """What the forecast says for one LGA, ready to store."""

    lga: str
    cells: int
    rain_ifs_mm: list[float]
    rain_ifs_max_mm: list[float]
    rain_aifs_mm: list[float] | None
    chance: dict[int, list[int]] | None
    temp_dawn_c: list[float] | None
    temp_afternoon_c: list[float] | None


def _polygons(geometry: dict) -> list[list]:
    """A GeoJSON Polygon or MultiPolygon as a list of polygons (lists of rings)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"unsupported geometry {geometry['type']!r}")


def points_in_geometry(xs: np.ndarray, ys: np.ndarray, geometry: dict) -> np.ndarray:
    """Vectorised even-odd test: which (xs, ys) fall inside the outline."""
    inside = np.zeros(xs.shape, dtype=bool)
    for polygon in _polygons(geometry):
        in_poly = np.zeros(xs.shape, dtype=bool)
        for ring in polygon:            # holes flip the parity back, as they should
            r = np.asarray(ring, dtype=np.float64)
            for (x1, y1), (x2, y2) in zip(r[:-1], r[1:], strict=True):
                if y1 == y2:
                    continue
                crosses = ((y1 > ys) != (y2 > ys)) & (xs < (x2 - x1) * (ys - y1) / (y2 - y1) + x1)
                in_poly ^= crosses
        inside |= in_poly
    return inside


def outline_bbox(geometry: dict) -> tuple[float, float, float, float]:
    """(lon_min, lat_min, lon_max, lat_max) of a Polygon or MultiPolygon."""
    pts = np.concatenate([np.asarray(ring, dtype=np.float64)
                          for polygon in _polygons(geometry) for ring in polygon])
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def lattice_inside(geometry: dict) -> tuple[np.ndarray, np.ndarray]:
    """The SUB_STEP lattice points that fall inside the outline, as (xs, ys).

    Shared by the forecast grid (0.25 deg) and IMERG's (0.1 deg,
    processors/rain_check.py), so both sides of the forecast check weight an
    LGA's area in exactly the same way.
    """
    x0, y0, x1, y1 = outline_bbox(geometry)
    xs1 = np.arange(np.floor(x0 / SUB_STEP), np.ceil(x1 / SUB_STEP)) * SUB_STEP + SUB_STEP / 2
    ys1 = np.arange(np.floor(y0 / SUB_STEP), np.ceil(y1 / SUB_STEP)) * SUB_STEP + SUB_STEP / 2
    xs, ys = np.meshgrid(xs1, ys1)
    xs, ys = xs.ravel(), ys.ravel()
    inside = points_in_geometry(xs, ys, geometry)
    if not inside.any():
        # Smaller than the lattice: the one point at its middle.
        return np.array([(x0 + x1) / 2]), np.array([(y0 + y1) / 2])
    return xs[inside], ys[inside]


def area_weights(geometry: dict, domain: Domain) -> Weights:
    """Share of the LGA's area in each domain cell it overlaps."""
    xs, ys = lattice_inside(geometry)
    rows = np.rint((domain.lat0 - ys) / RES).astype(np.int64)
    cols = np.rint((xs - domain.lon0) / RES).astype(np.int64)
    n_rows, n_cols = domain.shape
    if rows.min() < 0 or cols.min() < 0 or rows.max() >= n_rows or cols.max() >= n_cols:
        raise ValueError("LGA outline falls outside the forecast domain")
    flat = rows * n_cols + cols
    cells, inverse = np.unique(flat, return_inverse=True)
    share = np.bincount(inverse, weights=np.cos(np.radians(ys)))
    return Weights(rows=cells // n_cols, cols=cells % n_cols, share=share / share.sum())


def daily_totals(accumulated: Sequence[np.ndarray], scale: float = 1.0) -> list[np.ndarray]:
    """Accumulated-from-step-0 fields at 24 h, 48 h, ... -> each day's own total.

    Differences can dip a hair below zero from packing precision; that is
    clipped, since a day cannot un-rain.
    """
    out: list[np.ndarray] = []
    previous = np.zeros_like(accumulated[0])
    for acc in accumulated:
        out.append(np.clip((acc - previous) * scale, 0.0, None))
        previous = acc
    return out


def _mean(w: Weights, grid: np.ndarray) -> float:
    v = grid[w.rows, w.cols].astype(np.float64)
    ok = ~np.isnan(v)
    if not ok.any():
        return float("nan")
    return float(np.sum(v[ok] * w.share[ok]) / np.sum(w.share[ok]))


def _max(w: Weights, grid: np.ndarray) -> float:
    return float(np.nanmax(grid[w.rows, w.cols]))


def summarise(lga: str, w: Weights, f: ForecastFields) -> LgaForecast:
    """The stored forecast for one LGA. Rain to 0.1 mm, chances to whole %, temps to 0.1 C."""
    def mm(grids: list[np.ndarray] | None) -> list[float] | None:
        return None if grids is None else [round(_mean(w, g), 1) for g in grids]

    def celsius(grids: list[np.ndarray] | None) -> list[float] | None:
        return None if grids is None else [round(_mean(w, g), 1) for g in grids]

    return LgaForecast(
        lga=lga,
        cells=w.cells,
        rain_ifs_mm=mm(f.rain_ifs) or [],
        rain_ifs_max_mm=[round(_max(w, g), 1) for g in f.rain_ifs],
        rain_aifs_mm=mm(f.rain_aifs),
        chance=None if f.chances is None else {
            t: [int(round(_mean(w, g))) for g in grids] for t, grids in f.chances.items()},
        temp_dawn_c=celsius(f.temp_dawn),
        temp_afternoon_c=celsius(f.temp_afternoon),
    )


@dataclass(frozen=True, slots=True)
class CellWindow:
    """The raw cells over one tenant, for the map's "28 km cells" layer."""

    r0: int                  # first row, relative to the domain
    c0: int                  # first column, relative to the domain
    n_rows: int
    n_cols: int
    lat0: float              # centre latitude of the first (northernmost) row
    lon0: float              # centre longitude of the first (westernmost) column

    def take(self, grid: np.ndarray, digits: int = 1) -> list[float]:
        """This window of a domain grid, row-major, rounded (NaN -> 0)."""
        part = grid[self.r0:self.r0 + self.n_rows, self.c0:self.c0 + self.n_cols]
        return [round(float(v), digits) for v in np.nan_to_num(part).ravel()]


def window_for(domain: Domain, bbox: tuple[float, float, float, float], margin: int = 1) -> CellWindow:
    """Cells covering a tenant's box plus a margin, clipped to the domain."""
    lon_min, lat_min, lon_max, lat_max = bbox
    r0 = max(0, int(np.rint((domain.lat0 - lat_max) / RES)) - margin)
    r1 = min(domain.shape[0] - 1, int(np.rint((domain.lat0 - lat_min) / RES)) + margin)
    c0 = max(0, int(np.rint((lon_min - domain.lon0) / RES)) - margin)
    c1 = min(domain.shape[1] - 1, int(np.rint((lon_max - domain.lon0) / RES)) + margin)
    return CellWindow(r0=r0, c0=c0, n_rows=r1 - r0 + 1, n_cols=c1 - c0 + 1,
                      lat0=domain.lat0 - r0 * RES, lon0=domain.lon0 + c0 * RES)
