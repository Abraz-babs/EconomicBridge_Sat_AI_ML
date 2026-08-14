"""Does our NDVI drought signal track independently measured rainfall deficit?

WHY
---
`processors/ndvi_climatology.py` fixed a real defect: the old detector compared
the last three NDVI readings to the three before them, which measured the season
rather than the drought. The fix judges each LGA against its own normal for that
calendar month, and the seasonal artefact is demonstrably gone.

That is where the evidence stopped. We showed the detector no longer fires on
the calendar; we did NOT show that what it now fires on is drought. Those are
different claims and only the first was earned.

There is no drought ground truth available to us. FEWS NET IPC is reachable
without a key, but it classifies FOOD INSECURITY, which in Nigeria is driven
mostly by conflict, displacement and prices — validating a vegetation index
against it would largely measure how well our satellite sees insecurity, and an
agreement would be spurious.

So this asks a physically honest question instead:

    when the detector says an LGA is unusually dry for the time of year,
    was that LGA actually short of rain?

Vegetation greenness (Sentinel-2 NDVI) and precipitation (NASA GPM IMERG) are
independent measurements from different instruments. Agreement is corroboration.
Disagreement means the detector fires on something other than water — which is
exactly what we would want to know before quoting it to anyone.

WHAT THIS IS NOT
----------------
Not an accuracy figure. Rainfall deficit is a CAUSE of agricultural drought, not
a label saying drought occurred. A confirmed relationship supports the sentence
"our drought signal tracks independently measured rainfall deficits". It does
not support "our drought detection is N% accurate", and that sentence must not
be written on the strength of this script.

METHOD
------
* NDVI monthly history per LGA from public.lga_signal_history (2023-01 onward).
* Detections replayed leave-one-year-out, so a year is never judged against a
  normal built from itself.
* Rainfall from GPM_3IMERGM.07 — the monthly FINAL run. Final lags ~3.5 months,
  which is useless for warning anyone and ideal for backtesting.
* Rainfall anomaly is computed the same way as the NDVI anomaly: this month
  against this LGA's own normal for that calendar month, in standard deviations.
* Lags 0, 1 and 2 months are all tested, because vegetation responds to rain
  AFTER it falls. A relationship that appears only at lag 0 would be suspicious;
  one that strengthens at lag 1-2 is what soil moisture physics predicts.

Run (ingestion service, needs EARTHDATA_TOKEN + DATABASE_URL):
    python -m scripts.validate_drought_vs_rainfall
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import statistics as st
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from config import get_settings
from processors.ndvi_climatology import build_climatology, seasonal_drought
from sources.gpm_imerg import _lat_index, _lon_index, _parse_region_ascii

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Monthly FINAL run. Different collection, different granule shape and a
# flatter path (/YYYY/ with no month directory) than the daily Late run, which
# is why this does not reuse ImergClient's granule builder.
_ROOT = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGM.07"
_GRANULE = "3B-MO.MS.MRG.3IMERG.{ym}01-S000000-E235959.{mm}.V07{minor}.HDF5"
_MINORS = ("B", "A", "C")

# West Africa window covering every pilot tenant (Senegal in the west through
# Nigeria in the east). One request per month instead of 447.
_LON_MIN, _LON_MAX = -18.0, 16.0
_LAT_MIN, _LAT_MAX = 3.0, 17.0

_TIMEOUT = httpx.Timeout(180.0, connect=30.0)
_MIN_YEARS = 2          # same bar as the NDVI climatology
_MIN_STD = 0.05         # mm/day floor; a place with no rainfall variance at all


def _lga_centroids() -> dict[str, list[dict]]:
    p = Path(__file__).resolve().parents[1] / "data" / "lga_centroids.json"
    return json.loads(p.read_text(encoding="utf-8"))


async def _fetch_month(client: httpx.AsyncClient, year: int, month: int,
                       token: str) -> dict[int, list[float]] | None:
    """Regional monthly rainfall grid, or None if the granule is unavailable."""
    lo_lon, hi_lon = _lon_index(_LON_MIN), _lon_index(_LON_MAX)
    lo_lat, hi_lat = _lat_index(_LAT_MIN), _lat_index(_LAT_MAX)
    constraint = (
        f"precipitation[0:1:0][{lo_lon}:1:{hi_lon}][{lo_lat}:1:{hi_lat}]"
    )
    for minor in _MINORS:
        g = _GRANULE.format(ym=f"{year}{month:02d}", mm=f"{month:02d}", minor=minor)
        url = f"{_ROOT}/{year}/{g}.ascii?{constraint}"
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            return _parse_region_ascii(r.text)
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"IMERG {r.status_code}: Earthdata token rejected. The token "
                f"powers LAADS too, but GES DISC needs 'NASA GESDISC DATA "
                f"ARCHIVE' approved separately at urs.earthdata.nasa.gov."
            )
    return None


def _sample(grid: dict[int, list[float]], lon: float, lat: float) -> float | None:
    """Mean of the valid cells in a 3x3 window around a centroid, mm/day."""
    lon_i, lat_i = _lon_index(lon), _lat_index(lat)
    base_lat = _lat_index(_LAT_MIN)
    vals: list[float] = []
    for li in (lon_i - 1, lon_i, lon_i + 1):
        col = grid.get(li)
        if not col:
            continue
        for lj in (lat_i - 1, lat_i, lat_i + 1):
            k = lj - base_lat
            if 0 <= k < len(col) and col[k] > -9000.0:
                vals.append(col[k])
    return st.mean(vals) if vals else None


async def main() -> None:
    s = get_settings()
    token = getattr(s, "earthdata_token", "") or ""
    if not token:
        raise SystemExit("EARTHDATA_TOKEN not set")

    engine = create_async_engine(s.database_url)
    async with engine.begin() as c:
        rows = (await c.execute(text(
            "SELECT tenant_id, lga, EXTRACT(YEAR FROM period_start)::int, "
            "EXTRACT(MONTH FROM period_start)::int, mean "
            "FROM public.lga_signal_history "
            "WHERE signal='ndvi' AND mean IS NOT NULL"
        ))).all()
    await engine.dispose()
    obs = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    periods = sorted({(y, m) for _, _, y, m, _ in obs})
    log.info("NDVI: %d rows, %d months", len(obs), len(periods))

    # ── rainfall, one request per month ───────────────────────────────────
    centroids = _lga_centroids()
    rain: dict[tuple[str, str, int, int], float] = {}
    missing = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, (y, m) in enumerate(periods, 1):
            try:
                grid = await _fetch_month(client, y, m, token)
            except Exception as exc:  # noqa: BLE001 — one bad month must not kill the run
                log.warning("  %d-%02d fetch failed: %r", y, m, exc)
                grid = None
            if not grid:
                missing += 1
                continue
            for tenant, lgas in centroids.items():
                for row in lgas:
                    v = _sample(grid, row["lon"], row["lat"])
                    if v is not None:
                        rain[(tenant, row["lga"], y, m)] = v
            if i % 6 == 0 or i == len(periods):
                log.info("  fetched %d/%d months (%d samples)", i, len(periods), len(rain))
    log.info("rainfall: %d LGA-months, %d months unavailable", len(rain), missing)
    if not rain:
        raise SystemExit("no rainfall retrieved — cannot compare")

    # ── rainfall normals, same shape as the NDVI climatology ──────────────
    buckets: dict[tuple[str, str, int], list[float]] = collections.defaultdict(list)
    for (tenant, lga, _y, m), v in rain.items():
        buckets[(tenant, lga, m)].append(v)
    rain_norm = {
        k: (st.mean(v), st.pstdev(v) if len(v) > 1 else 0.0, len(v))
        for k, v in buckets.items()
    }

    def rain_z(tenant: str, lga: str, y: int, m: int) -> float | None:
        v = rain.get((tenant, lga, y, m))
        n = rain_norm.get((tenant, lga, m))
        if v is None or n is None or n[2] < _MIN_YEARS:
            return None
        return (v - n[0]) / max(n[1], _MIN_STD)

    # ── replay detections leave-one-year-out ──────────────────────────────
    fired: list[tuple[str, str, int, int]] = []
    quiet: list[tuple[str, str, int, int]] = []
    for y in sorted({o[2] for o in obs}):
        clim = build_climatology(obs, exclude_year=y)
        for tenant, lga, oy, om, val in obs:
            if oy != y:
                continue
            cell = clim.cell(tenant, lga, om)
            if cell is None or not cell.usable:
                continue
            key = (tenant, lga, oy, om)
            if seasonal_drought(val, clim, tenant=tenant, lga=lga, month=om):
                fired.append(key)
            else:
                quiet.append(key)
    log.info("detections: %d fired, %d quiet", len(fired), len(quiet))

    # ── the comparison, at three lags ─────────────────────────────────────
    def shifted(key, lag: int):
        tenant, lga, y, m = key
        m -= lag
        while m < 1:
            m += 12
            y -= 1
        return tenant, lga, y, m

    print("\nRainfall anomaly (sigma) when the drought detector fired vs stayed quiet")
    print("Negative = drier than that LGA's normal for that month.\n")
    print(f"{'lag':>4} {'n_fired':>8} {'fired_mean':>11} {'n_quiet':>8} "
          f"{'quiet_mean':>11} {'separation':>11} {'%fired dry':>11}")
    for lag in (0, 1, 2):
        fz = [z for k in fired if (z := rain_z(*shifted(k, lag))) is not None]
        qz = [z for k in quiet if (z := rain_z(*shifted(k, lag))) is not None]
        if not fz or not qz:
            print(f"{lag:>4} insufficient overlap")
            continue
        sep = st.mean(qz) - st.mean(fz)
        dry = sum(1 for z in fz if z < 0) / len(fz) * 100
        print(f"{lag:>4} {len(fz):>8} {st.mean(fz):>11.3f} {len(qz):>8} "
              f"{st.mean(qz):>11.3f} {sep:>11.3f} {dry:>10.1f}%")

    print("\nReading it: a NEGATIVE fired_mean and a POSITIVE separation mean the")
    print("detector fires where rain was genuinely short. Separation near zero")
    print("means the signal is unrelated to rainfall — which would be the")
    print("finding, and would need saying plainly rather than burying.")


if __name__ == "__main__":
    asyncio.run(main())
