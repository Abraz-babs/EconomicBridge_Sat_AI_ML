"""Village light — which real villages are dark at night, and who lives there.

Economic Visibility's answer to one practical question: which of a state's
villages show no light at night, and how many people and young children live
in them? Those are the likeliest to be off-grid and underserved — the first
stops for electrification, cash-transfer enrolment, immunisation and aid.

For every GRID3-named village of a pilot state (public.named_settlements):
  * night light — NASA VIIRS Black Marble (VNP46A2, 500 m) as a 12-night
    median on clear dry-season nights, and again in the wet season as a check
    (measured 2026-09-24: the two agree for ~99% of unlit villages);
  * people and children under five — Meta & CIESIN HRSL (30 m, CC BY 4.0),
    each populated pixel assigned ONCE, to its nearest village within 1 km.
    Towns carry several GRID3 points (one per quarter); summing a circle per
    point would count the same people two and three times.

It measures light visible from space, not income: "unlit" means below what the
satellite detects, not proof of no electricity. The panel says so.

Rows go to tenant_<id>.village_light (migration 0054), one per village per
yearly round. Seasonal and manual, like the land-change scan:

    python -m scripts.run_village_light --tenant kebbi,fct
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from scipy.spatial import cKDTree
from sqlalchemy import text

from config import get_settings
from db import get_session_factory, set_tenant_schema
from sources.viirs_raster import sample_radiance

log = logging.getLogger(__name__)

SOURCE = "village_light_v1"
SOURCES_LABEL = ("NASA VIIRS Black Marble VNP46A2 (12-night medians); "
                 "Meta & CIESIN HRSL population (CC BY 4.0); GRID3 settlement names (CC BY 4.0)")

# nW/cm²/sr. Below UNLIT the satellite detects no light at the village.
UNLIT, DIM = 0.5, 2.0
NIGHTS = 12
RADIUS_KM = 1.0
CHUNK_DEG = 0.5

HRSL = "/vsicurl/https://dataforgood-fb-data.s3.amazonaws.com/hrsl-cogs/"
HRSL_PEOPLE = HRSL + "hrsl_general/hrsl_general-latest.vrt"
HRSL_UNDER5 = HRSL + "hrsl_children_under_five/hrsl_children_under_five-latest.vrt"

# Pilot tenant -> GRID3 statename (GRID3 spells the capital territory "Fct").
GRID3_STATE = {
    "kebbi": "Kebbi", "zamfara": "Zamfara", "niger": "Niger", "kaduna": "Kaduna",
    "benue": "Benue", "plateau": "Plateau", "nasarawa": "Nasarawa", "fct": "Fct",
}


def classify(radiance: float | None) -> str:
    if radiance is None:
        return "unknown"
    return "unlit" if radiance < UNLIT else "dim" if radiance < DIM else "lit"


def assign_to_nearest(
    px_xy: np.ndarray, values: np.ndarray, village_xy: np.ndarray, radius_km: float,
) -> tuple[np.ndarray, float]:
    """Sum each pixel's value into its nearest village within radius_km.

    Coordinates are in km on a local plane. Returns (per-village totals, the
    total that fell beyond every village's radius). Every pixel lands in at
    most one village, so the totals add up and nothing is counted twice.
    """
    out = np.zeros(len(village_xy))
    if len(px_xy) == 0 or len(village_xy) == 0:
        return out, float(values.sum()) if len(values) else 0.0
    dist, idx = cKDTree(village_xy).query(px_xy, distance_upper_bound=radius_km)
    hit = np.isfinite(dist)
    np.add.at(out, idx[hit], values[hit])
    return out, float(values[~hit].sum())


@dataclass
class Village:
    settlement_id: int
    name: str
    ward: str | None
    lga: str | None
    lon: float
    lat: float


async def night_light(points: list[tuple[float, float]], end: date) -> tuple[dict, str]:
    """12-night median radiance per point, walking back from `end`.

    Nights with too little readable coverage are skipped rather than averaged
    in. Returns ({point: median or None}, 'first..last' window actually used).
    """
    s = get_settings()
    kw = dict(base_url=s.earthdata_laads_base_url, collection=s.earthdata_laads_collection,
              product=s.viirs_black_marble_product, token=s.earthdata_token)
    per_point: dict[tuple[float, float], list[float]] = {p: [] for p in points}
    used: list[date] = []
    for k in range(NIGHTS * 2):
        if len(used) >= NIGHTS:
            break
        day = end - timedelta(days=k)
        got = await sample_radiance(points, day=day, max_lookback_days=0, **kw)
        vals = [(p, got[p].radiance) for p in points if got.get(p) and got[p].radiance is not None]
        if len(vals) < 0.5 * len(points):
            continue
        used.append(day)
        for p, v in vals:
            per_point[p].append(v)
    window = f"{min(used)}..{max(used)}" if used else ""
    return {p: (statistics.median(v) if v else None) for p, v in per_point.items()}, window


def population(url: str, villages: list[Village]) -> tuple[np.ndarray, float]:
    """HRSL people assigned to their nearest village, read chunk by chunk."""
    import rasterio
    from rasterio.windows import from_bounds

    lons = np.array([v.lon for v in villages])
    lats = np.array([v.lat for v in villages])
    kx = 111.32 * math.cos(math.radians(float(lats.mean())))
    v_xy = np.column_stack([lons * kx, lats * 111.32])
    totals = np.zeros(len(villages))
    beyond = 0.0
    lo0, lo1 = lons.min() - 0.02, lons.max() + 0.02
    la0, la1 = lats.min() - 0.02, lats.max() + 0.02
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.vrt"):
        with rasterio.open(url) as ds:
            for cx in np.arange(lo0, lo1, CHUNK_DEG):
                for cy in np.arange(la0, la1, CHUNK_DEG):
                    win = from_bounds(cx, cy, min(cx + CHUNK_DEG, lo1), min(cy + CHUNK_DEG, la1),
                                      ds.transform).round_offsets().round_lengths()
                    arr = ds.read(1, window=win)
                    ok = np.isfinite(arr) & (arr > 0)
                    if not ok.any():
                        continue
                    rr, cc = np.nonzero(ok)
                    t = ds.window_transform(win)
                    px = np.column_stack([(t.c + (cc + 0.5) * t.a) * kx, (t.f + (rr + 0.5) * t.e) * 111.32])
                    part, out = assign_to_nearest(px, arr[ok].astype(float), v_xy, RADIUS_KM)
                    totals += part
                    beyond += out
    return totals, beyond


UPSERT = text("""
    INSERT INTO village_light (
        settlement_id, name, ward, lga, geom, period, radiance_dry, radiance_wet,
        light_class, light_class_wet, people, under5, dry_window, wet_window, sources
    ) VALUES (
        :sid, :name, :ward, :lga, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :period,
        :rad_dry, :rad_wet, :cls, :cls_wet, :people, :under5, :dry_window, :wet_window, :sources
    )
    ON CONFLICT (settlement_id, period) DO UPDATE SET
        radiance_dry = EXCLUDED.radiance_dry, radiance_wet = EXCLUDED.radiance_wet,
        light_class = EXCLUDED.light_class, light_class_wet = EXCLUDED.light_class_wet,
        people = EXCLUDED.people, under5 = EXCLUDED.under5,
        dry_window = EXCLUDED.dry_window, wet_window = EXCLUDED.wet_window,
        sources = EXCLUDED.sources, measured_at = NOW()
    WHERE (village_light.radiance_dry, village_light.radiance_wet, village_light.people,
           village_light.under5, village_light.light_class, village_light.light_class_wet)
      IS DISTINCT FROM
          (EXCLUDED.radiance_dry, EXCLUDED.radiance_wet, EXCLUDED.people,
           EXCLUDED.under5, EXCLUDED.light_class, EXCLUDED.light_class_wet)
""")


async def scan_tenant(tenant: str, *, dry_end: date, wet_end: date, period: str,
                      write: bool = True) -> str:
    state = GRID3_STATE.get(tenant)
    if state is None:
        return "skipped: no GRID3 village names for this tenant"
    factory = get_session_factory()
    async with factory() as s:
        villages = [Village(int(r[0]), r[1], r[2], r[3], float(r[4]), float(r[5])) for r in (await s.execute(text(
            "SELECT id, name, ward, lga, ST_X(geom), ST_Y(geom) FROM public.named_settlements "
            "WHERE state = :s ORDER BY id"), {"s": state})).all()]
    if not villages:
        return "skipped: named_settlements empty for this state (run scripts.load_grid3_settlements)"
    points = [(v.lon, v.lat) for v in villages]
    dry, dry_window = await night_light(points, dry_end)
    wet, wet_window = await night_light(points, wet_end)
    people, _beyond = population(HRSL_PEOPLE, villages)
    under5, _ = population(HRSL_UNDER5, villages)
    rows = [{
        "sid": v.settlement_id, "name": v.name, "ward": v.ward, "lga": v.lga,
        "lon": v.lon, "lat": v.lat, "period": period,
        "rad_dry": None if dry[(v.lon, v.lat)] is None else round(dry[(v.lon, v.lat)], 3),
        "rad_wet": None if wet[(v.lon, v.lat)] is None else round(wet[(v.lon, v.lat)], 3),
        "cls": classify(dry[(v.lon, v.lat)]), "cls_wet": classify(wet[(v.lon, v.lat)]),
        "people": int(round(people[i])), "under5": int(round(under5[i])),
        "dry_window": dry_window, "wet_window": wet_window, "sources": SOURCES_LABEL,
    } for i, v in enumerate(villages)]
    unlit = [r for r in rows if r["cls"] == "unlit"]
    summary = (f"{len(unlit)}/{len(rows)} villages unlit (dry {dry_window}, wet {wet_window}); "
               f"{sum(r['people'] for r in unlit):,} people, {sum(r['under5'] for r in unlit):,} under five")
    if write:
        async with factory() as s:
            await set_tenant_schema(s, tenant)
            for i in range(0, len(rows), 1000):
                await s.execute(UPSERT, rows[i:i + 1000])
            await s.commit()
    return summary


async def run_village_light_scan(tenants: list[str], *, dry_end: date, wet_end: date,
                                 period: str | None = None, write: bool = True) -> dict[str, str]:
    period = period or str(dry_end.year)
    out: dict[str, str] = {}
    for t in tenants:
        try:
            out[t] = await scan_tenant(t, dry_end=dry_end, wet_end=wet_end, period=period, write=write)
        except Exception as exc:  # noqa: BLE001 — one state failing must not stop the rest
            log.exception("village light failed tenant=%s", t)
            out[t] = f"FAILED: {exc!r}"
        log.info("village light %s: %s", t, out[t])
    return out
