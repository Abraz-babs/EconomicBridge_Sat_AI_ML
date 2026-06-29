"""Real VIIRS Black Marble (VNP46A2) night-light radiance sampler.

Reads TRUE per-pixel night-light radiance (nW/cm²/sr) at any coordinate from
NASA's daily Black Marble product — replacing the catalog-only / hash-proxy path
in processors/poverty_signals.py. Public-domain NASA data (LAADS DAAC); free for
commercial use with attribution ("NASA Black Marble VNP46A2, LAADS DAAC").

Pipeline:
  1. tile_for(lon, lat) → the 10°×10° geographic tile (hHHvVV) a point falls in.
  2. download_tile(...)  → fetch that day's granule from LAADS (bearer token),
                           disk-cached so each tile is pulled once per day.
  3. sample_granule(...) → open the HDF5, read the GAP-FILLED DNB radiance grid,
                           and map each coordinate to a pixel via the granule's
                           own `lat`/`lon` arrays (exact — no projection guessing).

Verified live against Nigerian cities (Kano ≈27, Kaduna ≈17 nW/cm²/sr) vs. remote
bush (≈0.05): bright where lit, dark where empty. A new light in normally-dark
farmland is a year-round "new human activity" signal (encroachment / settlement),
available every night regardless of season — unlike fire or wet-season NDVI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

log = logging.getLogger(__name__)

# HDF5 layout (VNP46A2 collection 5200) — verified against a live granule.
_GRID = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/"
NTL_GAPFILLED = _GRID + "Gap_Filled_DNB_BRDF-Corrected_NTL"
NTL_RAW = _GRID + "DNB_BRDF-Corrected_NTL"
QF_FLAG = _GRID + "Mandatory_Quality_Flag"
LAT_DS = _GRID + "lat"
LON_DS = _GRID + "lon"
FILL_VALUE = -999.9
TILE_DEG = 10.0       # each Black Marble tile spans 10° lon × 10° lat
TILE_PX = 2400        # 2400×2400 pixels per tile (~500 m)

# Where downloaded granules are cached (one pull per tile per day). Overridable.
CACHE_DIR = Path("/tmp/viirs_black_marble")


@dataclass(frozen=True, slots=True)
class RadianceSample:
    """Night-light radiance at one coordinate, plus the NASA quality flag."""

    lon: float
    lat: float
    radiance: float | None     # nW/cm²/sr; None when the pixel is fill/no-data
    quality: int | None        # Mandatory_Quality_Flag (0 = high quality)


def tile_for(lon: float, lat: float) -> tuple[int, int]:
    """The (h, v) Black Marble tile a coordinate falls in.

    h00 starts at lon −180, v00 at lat +90, each tile 10°. Nigeria sits in
    h18/h19 × v07/v08.
    """
    h = int((lon + 180.0) // TILE_DEG)
    v = int((90.0 - lat) // TILE_DEG)
    return h, v


def sample_granule(
    h5_path: Path | str, points: list[tuple[float, float]],
) -> list[RadianceSample]:
    """Sample radiance at each (lon, lat) in a downloaded granule.

    Uses the granule's own `lat`/`lon` coordinate vectors for an exact nearest-
    pixel lookup, and prefers the gap-filled NTL layer (no cloud holes).
    Pure/synchronous so it is unit-testable against a synthetic granule.
    """
    import h5py

    with h5py.File(h5_path, "r") as hf:
        ds_name = NTL_GAPFILLED if NTL_GAPFILLED in hf else NTL_RAW
        ntl = hf[ds_name][:]
        lat = hf[LAT_DS][:]
        lon = hf[LON_DS][:]
        qf = hf[QF_FLAG][:] if QF_FLAG in hf else None

        lat_min, lat_max = float(lat.min()), float(lat.max())
        lon_min, lon_max = float(lon.min()), float(lon.max())

        out: list[RadianceSample] = []
        for plon, plat in points:
            if not (lon_min <= plon <= lon_max and lat_min <= plat <= lat_max):
                out.append(RadianceSample(plon, plat, None, None))
                continue
            r = int(np.argmin(np.abs(lat - plat)))
            c = int(np.argmin(np.abs(lon - plon)))
            val = float(ntl[r, c])
            # Fill is -999.9 (stored float32 reads back as -999.9000244, so an
            # exact compare misses — threshold instead; valid radiance is ≥ 0).
            radiance = None if val <= -999.0 else round(val, 3)
            quality = int(qf[r, c]) if qf is not None else None
            out.append(RadianceSample(plon, plat, radiance, quality))
        return out


async def _granule_name(
    http: httpx.AsyncClient, *, base_url: str, collection: str, product: str,
    day: date, h: int, v: int, token: str,
) -> str | None:
    """The granule filename for (product, day, tile) from the LAADS day listing."""
    ddd = day.timetuple().tm_yday
    url = f"{base_url}/archive/allData/{collection}/{product}/{day.year}/{ddd:03d}/.json"
    resp = await http.get(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=60.0,
    )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    rows = rows if isinstance(rows, list) else rows.get("content") or []
    tag = f"h{h:02d}v{v:02d}"
    for row in rows:
        name = row.get("name") or ""
        if tag in name and name.endswith(".h5"):
            return name
    return None


async def download_tile(
    http: httpx.AsyncClient, *, base_url: str, collection: str, product: str,
    day: date, h: int, v: int, token: str, cache_dir: Path = CACHE_DIR,
) -> Path | None:
    """Fetch (and disk-cache) the granule for one tile/day. None if unavailable."""
    name = await _granule_name(
        http, base_url=base_url, collection=collection, product=product,
        day=day, h=h, v=v, token=token,
    )
    if not name:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / name
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    ddd = day.timetuple().tm_yday
    url = (
        f"{base_url}/archive/allData/{collection}/{product}/"
        f"{day.year}/{ddd:03d}/{name}"
    )
    async with http.stream(
        "GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=300.0,
    ) as resp:
        if resp.status_code != 200 or "html" in (resp.headers.get("content-type") or ""):
            log.warning("viirs.download blocked tile=h%02dv%02d status=%s "
                        "(EULA/token?)", h, v, resp.status_code)
            return None
        with open(dest, "wb") as fh:
            async for chunk in resp.aiter_bytes(1 << 20):
                fh.write(chunk)
    return dest


async def sample_radiance(
    points: list[tuple[float, float]], *,
    base_url: str, collection: str, product: str, token: str,
    day: date | None = None, max_lookback_days: int = 4,
    http: httpx.AsyncClient | None = None, cache_dir: Path = CACHE_DIR,
) -> dict[tuple[float, float], RadianceSample]:
    """Real night-light radiance for many points: group by tile, pull each
    needed tile once (walking back a few days for the latest available), and
    sample. Points whose tile can't be fetched come back with radiance=None.
    """
    if not token:
        return {p: RadianceSample(p[0], p[1], None, None) for p in points}
    start = day or date.today()

    by_tile: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for plon, plat in points:
        by_tile.setdefault(tile_for(plon, plat), []).append((plon, plat))

    owns_http = http is None
    client = http or httpx.AsyncClient(follow_redirects=True)
    results: dict[tuple[float, float], RadianceSample] = {}
    try:
        for (h, v), tile_pts in by_tile.items():
            path: Path | None = None
            for back in range(max_lookback_days + 1):
                path = await download_tile(
                    client, base_url=base_url, collection=collection,
                    product=product, day=start - timedelta(days=back),
                    h=h, v=v, token=token, cache_dir=cache_dir,
                )
                if path:
                    break
            if not path:
                for p in tile_pts:
                    results[p] = RadianceSample(p[0], p[1], None, None)
                continue
            for s in sample_granule(path, tile_pts):
                results[(s.lon, s.lat)] = s
    finally:
        if owns_http:
            await client.aclose()
    return results
