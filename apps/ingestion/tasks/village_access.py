"""Travel time to care at every village — the Mobility Compass's access factor.

For each GRID3 village in the village layer (village_light, 0054), reads the
modelled time to the nearest health facility on two national surfaces from
the Data for Children Collaborative (University of Edinburgh / UNICEF, 2024,
CC BY 4.0):

    walking     on roads, tracks and open ground, at walking speed
    motorised   with a vehicle on roads, walking to the nearest road first

and stores both, in minutes, in tenant_<id>.village_access (0059) with the
people living at the village (Meta & CIESIN HRSL, as in the village layer).
The API rolls them up by LGA: people-weighted median minutes and the share of
people more than an hour's walk from care.

The rasters are national GeoTIFFs in seconds, stored in strips, read over
HTTP range requests (/vsicurl) one band of rows at a time — only the rows a
state's villages fall on. Measured 2026-09-27 on Zamfara and Kebbi: every
village sampled, a few minutes per state. The surfaces are a 2024 model and
do not change, so this runs once, then again only when the village layer
gains villages or Data for Children republishes.

UPSERT, NEVER DELETE (retention triggers keep any value a re-run changes).
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text

from db import get_session_factory, set_tenant_schema

log = logging.getLogger(__name__)

SOURCE = "d4c_travel_2024_v1"
RASTERS = {
    "walk_min": "/vsicurl/https://s3.eidf.ac.uk/eidf158-walkingtraveltimemaps/service_area_nga_walking.tif",
    "drive_min": "/vsicurl/https://s3.eidf.ac.uk/eidf158-motorised-travel-time-maps/service_area_nga_motorised.tif",
}
ROW_BAND = 256              # raster rows read per HTTP window
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "3",
}

UPSERT = text("""
    INSERT INTO village_access
        (settlement_id, name, ward, lga, geom, people, walk_min, drive_min, source)
    VALUES (:sid, :name, :ward, :lga, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            :people, :walk_min, :drive_min, :source)
    ON CONFLICT (settlement_id, source) DO UPDATE SET
        name = EXCLUDED.name, ward = EXCLUDED.ward, lga = EXCLUDED.lga, geom = EXCLUDED.geom,
        people = EXCLUDED.people, walk_min = EXCLUDED.walk_min, drive_min = EXCLUDED.drive_min,
        measured_at = NOW()
    WHERE (village_access.name, village_access.ward, village_access.lga, village_access.people,
           village_access.walk_min, village_access.drive_min, ST_AsBinary(village_access.geom))
      IS DISTINCT FROM
          (EXCLUDED.name, EXCLUDED.ward, EXCLUDED.lga, EXCLUDED.people,
           EXCLUDED.walk_min, EXCLUDED.drive_min, ST_AsBinary(EXCLUDED.geom))
""")


@dataclass
class AccessSummary:
    villages: int = 0
    sampled: dict[str, int] | None = None
    written: int = 0
    error: str | None = None

    def __str__(self) -> str:
        if self.error:
            return f"failed: {self.error}"
        got = ", ".join(f"{k} {v}" for k, v in (self.sampled or {}).items())
        return f"{self.villages} villages ({got}), {self.written} rows upserted"


def pixel_index(lon: np.ndarray, lat: np.ndarray, transform: Sequence[float],
                height: int, width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(rows, cols, inside) for points on a north-up grid.

    `transform` is the affine (a, b, c, d, e, f) — pixel width a, origin x c,
    pixel height e (negative), origin y f. Computed by hand because the
    container's rasterio rejects arrays in `index()`. Points off the grid are
    clamped for the read and flagged outside.
    """
    a, _b, c, _d, e, f = transform[:6]
    rr = np.floor((lat - f) / e).astype(int)
    cc = np.floor((lon - c) / a).astype(int)
    inside = (rr >= 0) & (rr < height) & (cc >= 0) & (cc < width)
    return np.clip(rr, 0, height - 1), np.clip(cc, 0, width - 1), inside


def to_minutes(seconds: np.ndarray) -> np.ndarray:
    """Seconds -> minutes; no-data (negative, NaN, infinite) becomes NaN."""
    out = np.asarray(seconds, dtype=float) / 60.0
    out[~np.isfinite(out) | (out < 0)] = np.nan
    return out


def _sample(url: str, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    import rasterio
    from rasterio.windows import Window

    with rasterio.Env(**GDAL_ENV), rasterio.open(url) as ds:
        rr, cc, inside = pixel_index(lon, lat, tuple(ds.transform), ds.height, ds.width)
        vals = np.full(len(lon), np.nan)
        nodata = ds.nodata
        for r0 in range(int(rr.min()), int(rr.max()) + 1, ROW_BAND):
            sel = (rr >= r0) & (rr < r0 + ROW_BAND) & inside
            if not sel.any():
                continue
            n = min(ROW_BAND, ds.height - r0)
            band = ds.read(1, window=Window(0, r0, ds.width, n))
            got = band[rr[sel] - r0, cc[sel]].astype(float)
            if nodata is not None and not math.isnan(nodata):
                got[got == nodata] = np.nan
            vals[sel] = got
    return to_minutes(vals)


async def run_village_access(tenants: Sequence[str], *, write: bool = True) -> dict[str, AccessSummary]:
    factory = get_session_factory()
    out: dict[str, AccessSummary] = {}
    for tenant in tenants:
        summary = AccessSummary()
        out[tenant] = summary
        try:
            async with factory() as session:
                await set_tenant_schema(session, tenant)
                rows = (await session.execute(text(
                    """
                    SELECT settlement_id, name, ward, lga, ST_X(geom) AS lon, ST_Y(geom) AS lat, people
                      FROM village_light
                     WHERE period = (SELECT max(period) FROM village_light)
                    """
                ))).mappings().all()
            summary.villages = len(rows)
            if not rows:
                summary.error = "no villages in the village layer"
                continue
            lon = np.array([float(r["lon"]) for r in rows])
            lat = np.array([float(r["lat"]) for r in rows])
            minutes = {}
            for col, url in RASTERS.items():
                minutes[col] = _sample(url, lon, lat)
                log.info("village access %s %s: %d of %d sampled", tenant, col,
                         int(np.isfinite(minutes[col]).sum()), len(rows))
            summary.sampled = {k: int(np.isfinite(v).sum()) for k, v in minutes.items()}
            if not write:
                continue

            def mins(col: str, i: int) -> float | None:
                v = minutes[col][i]
                return round(float(v), 1) if np.isfinite(v) else None

            payload = [{
                "sid": int(r["settlement_id"]), "name": r["name"], "ward": r["ward"], "lga": r["lga"],
                "lon": float(r["lon"]), "lat": float(r["lat"]), "people": int(r["people"] or 0),
                "walk_min": mins("walk_min", i), "drive_min": mins("drive_min", i), "source": SOURCE,
            } for i, r in enumerate(rows)]
            async with factory() as session:
                await set_tenant_schema(session, tenant)
                for i in range(0, len(payload), 2000):
                    await session.execute(UPSERT, payload[i:i + 2000])
                await session.commit()
            summary.written = len(payload)
        except Exception as exc:  # noqa: BLE001 — one state failing must not stop the rest
            summary.error = repr(exc)[:300]
            log.exception("village access %s failed", tenant)
    return out
