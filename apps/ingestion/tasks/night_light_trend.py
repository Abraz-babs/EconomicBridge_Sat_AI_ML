"""Night-light trend — the light each LGA and village shows, every year since 2012.

Mobility Compass's measure of economic activity: where towns and markets are
growing and where they are fading, from NASA Black Marble's YEARLY composites
(VNP46A4, collection 5200, 500 m). Each year has two composites of the same
nights — near-nadir (the satellite looking straight down, ~26 passes a year)
and all-angle (~140 passes) — and both are stored, because:

  * single years move with cloud and viewing angle: several pilot states dip
    together in 2017-2020 with steady pass counts and no known cause, so the
    module compares three-year averages (2012-14 with the latest three);
  * faint lights (0.5-1 nW) can read as gone on one composite and faintly
    present on the other — Benue had 24 villages "gone dark" on near-nadir
    and none on all-angle (measured 2026-09-27). A village or LGA change is
    shown only when BOTH composites agree.

For every LGA (tenant boundaries, sources/lga_boundaries.py): summed radiance
and the area lit at >= 1 nW/cm²/sr, per year and composite. For every GRID3
village of the latest village_light round (Nigerian pilots): the yearly
radiance at its pixel on both composites and a status:

  gone_dark  lit every year of 2012-14 (average >= 1 nW) and no light in any
             of the last three years on the near-nadir composite, confirmed
             below detection on average by the all-angle composite
  newly_lit  no light in any of 2012-14 and lit every one of the last three
             years (average >= 1 nW) on near-nadir, confirmed by all-angle
  steady     anything else

Light is activity, not income: a village can go dark because people left, a
grid line or generator stopped, or fuel got dearer. The module says so.

Rows go to tenant_<id>.lga_night_light and tenant_<id>.village_light_trend
(migration 0058), added per year, never overwritten. Yearly and manual:

    python -m scripts.run_night_light_trend --tenant kebbi,zamfara
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sqlalchemy import text

from config import get_settings
from db import get_session_factory, set_tenant_schema
from sources import lga_boundaries as lb
from sources.viirs_raster import download_tile

log = logging.getLogger(__name__)

PRODUCT = "VNP46A4"
SOURCE = "NASA Black Marble VNP46A4 (yearly, collection 5200)"
_GRID = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/"
COMPOSITES = {
    "near_nadir": _GRID + "NearNadir_Composite_Snow_Free",
    "all_angle": _GRID + "AllAngle_Composite_Snow_Free",
}
LIT_NW = 1.0         # a pixel counts as lit area from here
DARK_NW = 0.5        # below this the satellite sees no light (as village_light's "unlit")
WINDOW = 3           # years averaged at each end
PIXEL_DEG = 10.0 / 2400
KM_PER_DEG = 111.32


# ─── pure rules (unit-tested) ─────────────────────────────────────────────

def tiles_for(bboxes: list[tuple[float, float, float, float]]) -> list[tuple[int, int]]:
    """Every 10° Black Marble tile (h, v) touched by the given lon/lat boxes."""
    out: set[tuple[int, int]] = set()
    for lo0, la0, lo1, la1 in bboxes:
        for h in range(int((lo0 + 180) // 10), int((lo1 + 180) // 10) + 1):
            for v in range(int((90 - la1) // 10), int((90 - la0) // 10) + 1):
                out.add((h, v))
    return sorted(out)


def pixel_area_km2(lat: np.ndarray) -> np.ndarray:
    """Area of each row's 15-arc-second pixels at the given latitudes."""
    return (PIXEL_DEG * KM_PER_DEG) ** 2 * np.cos(np.radians(lat))


def lga_sums(ids: np.ndarray, radiance: np.ndarray, area: np.ndarray, n: int
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Summed radiance, lit area (km²) and pixel count per LGA id (0 = outside).

    ids and radiance are the tile grid; area is the per-row pixel area.
    Fill and negative values count as no light.
    """
    rad = np.where(radiance > 0, radiance, 0.0)
    flat = ids.ravel()
    area2d = np.broadcast_to(area[:, None], ids.shape).ravel()
    sums = np.bincount(flat, weights=rad.ravel(), minlength=n)
    lit = np.bincount(flat, weights=area2d * (rad.ravel() >= LIT_NW), minlength=n)
    px = np.bincount(flat, minlength=n)
    return sums, lit, px


def village_status(near: list[float | None], allang: list[float | None],
                   first_year: int) -> tuple[str, int | None]:
    """(status, since_year) for one village from its yearly series.

    The page says "lit in 2012-14, no light for the last three years" (and
    the reverse), so the rule says exactly that on the near-nadir composite —
    detected EVERY start year (average >= 1 nW) and in NONE of the last three
    years — and the all-angle composite, which keeps a faint residual glow
    from its many off-nadir passes, must confirm it on average.

    since_year: for gone_dark, the first year of the final run with no light;
    for newly_lit, the first year the light was detected.
    """
    def vals(xs: list[float | None]) -> list[float]:
        return [x for x in xs if x is not None]

    def avg(xs: list[float | None]) -> float | None:
        v = vals(xs)
        return sum(v) / len(v) if v else None

    def gone(s: list[float | None], strict: bool) -> bool:
        head, tail = s[:WINDOW], s[-WINDOW:]
        a, b = avg(head), avg(tail)
        if a is None or b is None or a < LIT_NW:
            return False
        if strict:
            return (len(vals(head)) == WINDOW and min(vals(head)) >= DARK_NW
                    and len(vals(tail)) == WINDOW and max(vals(tail)) < DARK_NW)
        return b < DARK_NW

    def new(s: list[float | None], strict: bool) -> bool:
        head, tail = s[:WINDOW], s[-WINDOW:]
        b = avg(tail)
        if not vals(head) or max(vals(head)) >= DARK_NW or b is None or b < LIT_NW:
            return False
        if strict:
            return (len(vals(head)) == WINDOW and len(vals(tail)) == WINDOW
                    and min(vals(tail)) >= DARK_NW)
        return True

    if len(near) < 2 * WINDOW or len(allang) != len(near):
        return "steady", None
    if gone(near, strict=True) and gone(allang, strict=False):
        since = None
        for i in range(len(near) - 1, -1, -1):
            if near[i] is None or near[i] >= DARK_NW:
                since = first_year + i + 1
                break
        return "gone_dark", since
    if new(near, strict=True) and new(allang, strict=False):
        first = next((first_year + i for i, x in enumerate(near) if (x or 0.0) >= DARK_NW), None)
        return "newly_lit", first
    return "steady", None


# ─── the run ──────────────────────────────────────────────────────────────

@dataclass
class TenantAcc:
    tenant: str
    lgas: list                                   # LgaBoundary, id = index + 1
    years: list[int]
    sums: dict = field(default_factory=dict)     # composite -> (n_lga+1, n_years)
    lit: dict = field(default_factory=dict)
    px: dict = field(default_factory=dict)
    villages: list = field(default_factory=list)  # (settlement_id, name, ward, lga, lon, lat, people)
    vrad: dict = field(default_factory=dict)      # composite -> (n_villages, n_years)


def _grid_ids(lgas: list, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    from affine import Affine
    from rasterio.features import rasterize

    px = float(lon[1] - lon[0])
    tr = Affine(px, 0, float(lon[0]), 0, -px, float(lat[0]))
    return rasterize([(b.geometry, i + 1) for i, b in enumerate(lgas)],
                     out_shape=(len(lat), len(lon)), transform=tr, fill=0, dtype="int32")


async def _load_villages(tenant: str) -> list[tuple]:
    factory = get_session_factory()
    async with factory() as s:
        await set_tenant_schema(s, tenant)
        has = (await s.execute(text("SELECT to_regclass('village_light') IS NOT NULL"))).scalar()
        if not has:
            return []
        rows = (await s.execute(text(
            "SELECT settlement_id, name, ward, lga, ST_X(geom), ST_Y(geom), people FROM village_light "
            "WHERE period = (SELECT max(period) FROM village_light) ORDER BY settlement_id"))).all()
    return [tuple(r) for r in rows]


LGA_UPSERT = text("""
    INSERT INTO lga_night_light (lga, year, composite, radiance_sum, lit_km2, pixels, source)
    VALUES (:lga, :year, :composite, :radiance_sum, :lit_km2, :pixels, :source)
    ON CONFLICT (lga, year, composite) DO UPDATE SET
        radiance_sum = EXCLUDED.radiance_sum, lit_km2 = EXCLUDED.lit_km2,
        pixels = EXCLUDED.pixels, source = EXCLUDED.source, measured_at = NOW()
    WHERE (lga_night_light.radiance_sum, lga_night_light.lit_km2, lga_night_light.pixels)
      IS DISTINCT FROM (EXCLUDED.radiance_sum, EXCLUDED.lit_km2, EXCLUDED.pixels)
""")

VILLAGE_UPSERT = text("""
    INSERT INTO village_light_trend (settlement_id, name, ward, lga, geom, people, first_year,
                                     last_year, near_nadir, all_angle, status, since_year, source)
    VALUES (:sid, :name, :ward, :lga, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :people,
            :first_year, :last_year, :near, :allang, :status, :since, :source)
    ON CONFLICT (settlement_id, last_year) DO UPDATE SET
        near_nadir = EXCLUDED.near_nadir, all_angle = EXCLUDED.all_angle,
        status = EXCLUDED.status, since_year = EXCLUDED.since_year, people = EXCLUDED.people,
        measured_at = NOW()
    WHERE (village_light_trend.near_nadir, village_light_trend.all_angle, village_light_trend.status,
           village_light_trend.since_year, village_light_trend.people)
      IS DISTINCT FROM (EXCLUDED.near_nadir, EXCLUDED.all_angle, EXCLUDED.status,
                        EXCLUDED.since_year, EXCLUDED.people)
""")


async def run_night_light_trend(tenants: list[str], *, first_year: int, last_year: int,
                                write: bool = True) -> dict[str, str]:
    """Measure every tenant's LGAs (and villages, where measured) for each year."""
    import h5py
    import httpx

    s = get_settings()
    years = list(range(first_year, last_year + 1))
    accs: list[TenantAcc] = []
    out: dict[str, str] = {}
    for t in tenants:
        lgas = list(lb.for_tenant(t))
        if not lgas:
            out[t] = "skipped: no LGA boundaries"
            continue
        acc = TenantAcc(t, lgas, years)
        acc.villages = await _load_villages(t)
        n = len(lgas) + 1
        for c in COMPOSITES:
            acc.sums[c] = np.zeros((n, len(years)))
            acc.lit[c] = np.zeros((n, len(years)))
            acc.px[c] = np.zeros((n, len(years)))
            acc.vrad[c] = np.full((len(acc.villages), len(years)), np.nan)
        accs.append(acc)
    if not accs:
        return out
    tiles = tiles_for([b.bbox for a in accs for b in a.lgas])
    log.info("night light: %d tenants, tiles %s, years %d-%d", len(accs), tiles, first_year, last_year)
    missing: list[str] = []
    async with httpx.AsyncClient(follow_redirects=True) as http:
        for (h, v) in tiles:
            grids: dict[str, tuple] = {}
            for yi, y in enumerate(years):
                path = await download_tile(http, base_url=s.earthdata_laads_base_url,
                                           collection=s.earthdata_laads_collection, product=PRODUCT,
                                           day=date(y, 1, 1), h=h, v=v, token=s.earthdata_token)
                if path is None:
                    missing.append(f"{y} h{h:02d}v{v:02d}")
                    continue
                with h5py.File(path, "r") as hf:
                    arrs = {c: hf[ds][:].astype("float64") for c, ds in COMPOSITES.items()}
                    lat = hf[_GRID + "lat"][:]
                    lon = hf[_GRID + "lon"][:]
                os.remove(path)
                area = pixel_area_km2(lat)
                for acc in accs:
                    key = acc.tenant
                    if key not in grids:
                        ids = _grid_ids(acc.lgas, lat, lon)
                        px = float(lon[1] - lon[0])
                        vx = np.array([r[4] for r in acc.villages]) if acc.villages else np.zeros(0)
                        vy = np.array([r[5] for r in acc.villages]) if acc.villages else np.zeros(0)
                        inside = (vx >= lon[0]) & (vx < lon[-1] + px) & (vy <= lat[0]) & (vy > lat[-1] - px)
                        vr = ((lat[0] - vy[inside]) / px).astype(int).clip(0, len(lat) - 1)
                        vc = ((vx[inside] - lon[0]) / px).astype(int).clip(0, len(lon) - 1)
                        grids[key] = (ids, np.nonzero(inside)[0], vr, vc)
                    ids, vidx, vr, vc = grids[key]
                    if not ids.any() and not len(vidx):
                        continue
                    for c, arr in arrs.items():
                        sums, lit, px_n = lga_sums(ids, arr, area, len(acc.lgas) + 1)
                        acc.sums[c][:, yi] += sums
                        acc.lit[c][:, yi] += lit
                        acc.px[c][:, yi] += px_n
                        if len(vidx):
                            # Fill (-999.9) is "no reading", not "no light": keep it unknown
                            # so a missing year can never make a village look dark.
                            got = arr[vr, vc]
                            acc.vrad[c][vidx, yi] = np.where(got >= 0, got, np.nan)
            log.info("night light: tile h%02dv%02d done", h, v)
    if missing:
        log.warning("night light: %d tile-years missing: %s", len(missing), ", ".join(missing[:20]))

    factory = get_session_factory()
    for acc in accs:
        lga_rows = []
        for i, b in enumerate(acc.lgas):
            for yi, y in enumerate(years):
                for c in COMPOSITES:
                    if acc.px[c][i + 1, yi] == 0:
                        continue
                    lga_rows.append({"lga": b.lga, "year": y, "composite": c,
                                     "radiance_sum": round(float(acc.sums[c][i + 1, yi]), 3),
                                     "lit_km2": round(float(acc.lit[c][i + 1, yi]), 3),
                                     "pixels": int(acc.px[c][i + 1, yi]), "source": SOURCE})
        v_rows = []
        counts = {"gone_dark": 0, "newly_lit": 0}
        for k, (sid, name, ward, lga, lon, lat, people) in enumerate(acc.villages):
            near = [None if math.isnan(x) else round(float(x), 3) for x in acc.vrad["near_nadir"][k]]
            allang = [None if math.isnan(x) else round(float(x), 3) for x in acc.vrad["all_angle"][k]]
            if all(x is None for x in near):
                continue
            status, since = village_status(near, allang, first_year)
            if status in counts:
                counts[status] += 1
            v_rows.append({"sid": sid, "name": name, "ward": ward, "lga": lga, "lon": lon, "lat": lat,
                           "people": int(people or 0), "first_year": first_year, "last_year": last_year,
                           "near": near, "allang": allang, "status": status, "since": since,
                           "source": SOURCE})
        summary = (f"{len(lga_rows)} LGA-year rows, {len(v_rows)} villages: "
                   f"{counts['gone_dark']} gone dark, {counts['newly_lit']} newly lit")
        if write:
            async with factory() as s2:
                await set_tenant_schema(s2, acc.tenant)
                for i in range(0, len(lga_rows), 1000):
                    await s2.execute(LGA_UPSERT, lga_rows[i:i + 1000])
                for i in range(0, len(v_rows), 1000):
                    await s2.execute(VILLAGE_UPSERT, v_rows[i:i + 1000])
                await s2.commit()
        out[acc.tenant] = summary
        log.info("night light %s: %s", acc.tenant, summary)
    return out
