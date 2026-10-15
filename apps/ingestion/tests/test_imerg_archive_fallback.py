"""IMERG archive fallback: when OPeNDAP refuses, read the same grid from whole files.

GES DISC OPeNDAP answered 503 to everything from 2026-10-13 while the plain
archive served the same granules. These tests pin the three things that make
the fallback safe: it returns the SAME cells the OPeNDAP subset would, it only
kicks in on a refusal (never on "not published"), and it downloads each granule
once per run however many regions read it.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from types import SimpleNamespace

import h5py
import httpx
import numpy as np
import pytest

from sources import gpm_imerg as gi
from sources import gpm_imerg_halfhourly as hh

FILL = -9999.9


def _granule(dataset: str, cells: dict[tuple[int, int], float]) -> bytes:
    """A real-layout IMERG file: precipitation[1][3600 lon][1800 lat], sparse."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        ds = f.create_dataset(dataset, shape=(1, 3600, 1800), dtype="f4",
                              chunks=(1, 100, 100), fillvalue=FILL)
        for (lon_i, lat_i), v in cells.items():
            ds[0, lon_i, lat_i] = v
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    async def instant(_s: float) -> None:
        return None
    monkeypatch.setattr(gi.asyncio, "sleep", instant)
    monkeypatch.setattr(hh.asyncio, "sleep", instant)


def _client(cls, handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = cls(http=http)
    c._settings = SimpleNamespace(earthdata_token="t")
    return c, http


# Kebbi-ish cell: 4.15E, 12.45N.
LON_I, LAT_I = gi._lon_index(4.15), gi._lat_index(12.45)


@pytest.mark.asyncio
async def test_daily_falls_back_to_the_archive_with_identical_cells() -> None:
    body = _granule("precipitation", {(LON_I, LAT_I): 31.25, (LON_I + 1, LAT_I): 2.5})
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if "/opendap/" in req.url.path:
            return httpx.Response(503)
        assert "Accept" not in req.headers or req.headers["Accept"] != "text/plain"
        if ".V07C." in req.url.path:
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    client, http = _client(gi.GpmImergClient, handler)
    grid = await client.region_grid(lon0=LON_I - 2, lon1=LON_I + 2,
                                    lat0=LAT_I - 2, lat1=LAT_I + 2,
                                    day=date(2026, 10, 12))
    await http.aclose()

    assert grid is not None
    assert grid.rows[LON_I][2] == pytest.approx(31.25)   # absolute lon key
    assert grid.rows[LON_I + 1][2] == pytest.approx(2.5)
    assert grid.rows[LON_I - 2][0] == pytest.approx(FILL, abs=0.01)
    rain = grid.sample(4.15, 12.45)
    assert rain is not None and rain.max_mm == pytest.approx(31.25)
    assert any("/data/GPM_L3/GPM_3IMERGDL.07/2026/10/" in c for c in calls)
    client.close()


@pytest.mark.asyncio
async def test_one_download_serves_every_region_and_opendap_is_not_retried() -> None:
    body = _granule("precipitation", {(LON_I, LAT_I): 7.0})
    opendap = archive = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal opendap, archive
        if "/opendap/" in req.url.path:
            opendap += 1
            return httpx.Response(503)
        archive += 1
        return httpx.Response(200, content=body)

    client, http = _client(gi.GpmImergClient, handler)
    day = date(2026, 10, 12)
    await client.region_grid(lon0=LON_I, lon1=LON_I + 3, lat0=LAT_I, lat1=LAT_I + 3, day=day)
    tripped_after = opendap
    await client.region_grid(lon0=LON_I - 9, lon1=LON_I, lat0=LAT_I - 9, lat1=LAT_I, day=day)
    await http.aclose()

    assert archive == 1                  # same granule, second region: no new download
    assert opendap == tripped_after      # tripped: OPeNDAP not asked again this run
    client.close()


@pytest.mark.asyncio
async def test_not_published_is_none_not_a_fallback() -> None:
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.path)
        return httpx.Response(404)

    client, http = _client(gi.GpmImergClient, handler)
    grid = await client.region_grid(lon0=1, lon1=2, lat0=1, lat1=2, day=date(2026, 10, 14))
    await http.aclose()
    assert grid is None
    assert all("/opendap/" in h for h in hits)          # never touched the archive
    assert not client._archive.tripped


@pytest.mark.asyncio
async def test_a_login_page_is_never_read_as_rain() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/opendap/" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(200, content=b"<!DOCTYPE html><title>Earthdata Login</title>")

    client, http = _client(gi.GpmImergClient, handler)
    with pytest.raises(gi.ImergError, match="not HDF5"):
        await client.region_grid(lon0=1, lon1=2, lat0=1, lat1=2, day=date(2026, 10, 12))
    await http.aclose()


@pytest.mark.asyncio
async def test_halfhourly_falls_back_with_offsets_like_opendap() -> None:
    body = _granule("Grid/precipitation", {(LON_I, LAT_I): 18.5})
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if "/opendap/" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(200, content=body)

    client, http = _client(hh.ImergHalfHourlyClient, handler)
    at = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    grid = await client.slice_grid(http, at=at, lon0=LON_I - 1, lon1=LON_I + 1,
                                   lat0=LAT_I - 1, lat1=LAT_I + 1)
    await http.aclose()

    assert grid is not None
    assert grid.rates[1][1] == pytest.approx(18.5)       # offsets from lon0/lat0
    assert grid.sample_max(4.15, 12.45) == pytest.approx(18.5)
    assert grid.peak() == pytest.approx(18.5)
    assert any(p.endswith("/data/GPM_L3/GPM_3IMERGHHL.07/2026/286/"
                          "3B-HHR-L.MS.MRG.3IMERG.20261013-S120000-E122959.0720.V07C.HDF5")
               for p in paths)
    client.close()


def test_close_deletes_the_downloads(tmp_path) -> None:
    arch = gi.ArchiveFallback("https://x", "precipitation")
    path = tmp_path / "g.h5"
    path.write_bytes(_granule("precipitation", {(10, 10): 1.0}))
    assert arch.subset(path, lon0=9, lon1=11, lat0=9, lat1=11)[1][1] == pytest.approx(1.0)
    arch._tmp = __import__("tempfile").TemporaryDirectory(prefix="imerg-test-")
    tmpdir = arch._tmp.name
    arch.close()
    arch.close()                                            # idempotent
    assert not __import__("os").path.exists(tmpdir)
    assert np.isclose(arch.subset(path, lon0=10, lon1=10, lat0=10, lat1=10)[0][0], 1.0)
