"""Open archive — catalogue paging, URL signing, tenant gating.

Hermetic by design: the STAC catalogue and the signing endpoint are
httpx.MockTransport. A test that quietly reached Planetary Computer would pass
on a laptop and fail in CI. Window reads are tested in test_cog_window.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from config import get_settings
from sources import open_archive as oa

STAC = "https://stac.test/api/stac/v1"
SAS = "https://sas.test/api/sas/v1"
NIGERIA = {"kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "nasarawa", "fct"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "open_archive_stac_url", STAC)
    monkeypatch.setattr(s, "open_archive_sas_url", SAS)
    monkeypatch.setattr(s, "open_archive_signing", "planetary_computer")
    oa._TOKENS.clear()
    yield
    oa._TOKENS.clear()


def _feature(fid, when, *, orbit="descending", rel=22, cloud=None):
    props = {"datetime": when, "sat:orbit_state": orbit,
             "sat:relative_orbit": rel, "platform": "sentinel-1c"}
    if cloud is not None:
        props["eo:cloud_cover"] = cloud
    return {"type": "Feature", "id": fid, "collection": oa.S1_RTC, "properties": props,
            "assets": {"vv": {"href": f"https://blob.test/{fid}/vv.tif"}}}


def _pages_transport(pages):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=pages[min(len(seen), len(pages)) - 1])
    return httpx.MockTransport(handler), seen


T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 15, tzinfo=timezone.utc)
BOX = (4.0, 11.5, 5.0, 12.5)


# ─── Catalogue search ─────────────────────────────────────────────────────


async def test_search_follows_every_page_dedupes_and_sorts_oldest_first():
    pages = [
        {"features": [_feature("b", "2026-09-10T17:54:00Z"), _feature("a", "2026-09-04T17:54:00Z")],
         "links": [{"rel": "next", "href": STAC + "/search?page=2",
                    "method": "POST", "body": {"token": "next:2"}}]},
        {"features": [_feature("c", "2026-09-12T05:10:00Z", orbit="ascending", rel=30),
                      _feature("b", "2026-09-10T17:54:00Z")],
         "links": []},
    ]
    transport, seen = _pages_transport(pages)
    async with httpx.AsyncClient(transport=transport) as c:
        scenes = await oa.search(oa.S1_RTC, BOX, T0, T1, client=c)

    assert [s.id for s in scenes] == ["a", "b", "c"]
    assert scenes[2].orbit_key == "ascending:30"
    first = json.loads(seen[0].content)
    assert first["collections"] == [oa.S1_RTC]
    assert first["datetime"] == "2026-09-01T00:00:00Z/2026-09-15T00:00:00Z"
    assert seen[1].method == "POST" and json.loads(seen[1].content) == {"token": "next:2"}


async def test_search_supports_get_style_next_links():
    pages = [
        {"features": [_feature("a", "2026-09-04T17:54:00Z")],
         "links": [{"rel": "next", "href": STAC + "/search?token=xyz", "method": "GET"}]},
        {"features": [_feature("b", "2026-09-05T17:54:00Z")], "links": []},
    ]
    transport, seen = _pages_transport(pages)
    async with httpx.AsyncClient(transport=transport) as c:
        scenes = await oa.search(oa.S1_RTC, BOX, T0, T1, client=c)
    assert [s.id for s in scenes] == ["a", "b"]
    assert seen[1].method == "GET"


async def test_a_truncated_search_says_so(monkeypatch, caplog):
    """Silently dropping scenes would read as "covered everything"."""
    monkeypatch.setattr(oa, "MAX_PAGES", 1)
    page = {"features": [_feature("a", "2026-09-04T17:54:00Z")],
            "links": [{"rel": "next", "href": STAC + "/search?page=2", "method": "POST"}]}
    transport, _ = _pages_transport([page])
    caplog.set_level(logging.WARNING)
    async with httpx.AsyncClient(transport=transport) as c:
        await oa.search(oa.S1_RTC, BOX, T0, T1, client=c)
    assert "truncated" in caplog.text


async def test_scenes_without_a_date_are_skipped_not_invented():
    page = {"features": [_feature("a", "2026-09-04T17:54:00Z"),
                         {"id": "nodate", "properties": {}, "assets": {}}], "links": []}
    transport, _ = _pages_transport([page])
    async with httpx.AsyncClient(transport=transport) as c:
        scenes = await oa.search(oa.S1_RTC, BOX, T0, T1, client=c)
    assert [s.id for s in scenes] == ["a"]


async def test_a_failing_catalogue_raises_one_clear_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, text="down"))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(oa.OpenArchiveError):
            await oa.search(oa.S1_RTC, BOX, T0, T1, client=c)


def test_optical_scenes_carry_no_orbit_key():
    s = oa.Scene(id="x", collection=oa.S2_L2A, datetime=T0, assets={}, cloud_cover=12.0)
    assert s.orbit_key is None


# ─── Signing ──────────────────────────────────────────────────────────────


def _sas(token="sv=2025&sig=SECRET", expiry=None):
    expiry = expiry or (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"msft:expiry": expiry, "token": token})
    return httpx.MockTransport(handler), calls


async def test_signing_caches_the_token_until_near_expiry():
    transport, calls = _sas()
    async with httpx.AsyncClient(transport=transport) as c:
        a = await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif", client=c)
        b = await oa.signed_href(oa.S1_RTC, "https://blob.test/y.tif?foo=1", client=c)
    assert len(calls) == 1
    assert str(calls[0].url) == SAS + "/token/" + oa.S1_RTC
    assert a == "https://blob.test/x.tif?sv=2025&sig=SECRET"
    assert b == "https://blob.test/y.tif?foo=1&sv=2025&sig=SECRET"


async def test_a_token_inside_its_expiry_margin_is_refetched():
    soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    transport, calls = _sas(expiry=soon)
    async with httpx.AsyncClient(transport=transport) as c:
        await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif", client=c)
        await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif", client=c)
    assert len(calls) == 2


async def test_the_signing_token_never_reaches_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    transport, _ = _sas()
    async with httpx.AsyncClient(transport=transport) as c:
        await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif", client=c)
    assert "SECRET" not in caplog.text
    assert "signing token refreshed" in caplog.text


async def test_public_catalogues_pass_urls_through_without_a_network_call(monkeypatch):
    monkeypatch.setattr(get_settings(), "open_archive_signing", "none")

    def boom(request):
        raise AssertionError("no network call expected")
    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
        assert await oa.signed_href(oa.S2_L2A, "https://x/y.tif", client=c) == "https://x/y.tif"


async def test_a_signing_answer_without_a_token_is_an_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"msft:expiry": None}))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(oa.OpenArchiveError):
            await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif", client=c)


async def test_an_unknown_signing_strategy_is_refused(monkeypatch):
    monkeypatch.setattr(get_settings(), "open_archive_signing", "guesswork")
    with pytest.raises(oa.OpenArchiveError):
        await oa.signed_href(oa.S1_RTC, "https://blob.test/x.tif")


# ─── Tenant gating: Nigeria live, Ghana + Senegal held ────────────────────


def _default_tenants() -> str:
    return type(get_settings()).model_fields["open_archive_tenants"].default


def test_nigeria_is_active_and_ghana_senegal_are_held_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "open_archive_tenants", _default_tenants())
    assert set(oa.active_tenants()) == NIGERIA
    assert oa.held_tenants() == ["ghana", "senegal"]


def test_enabling_ghana_is_a_config_change_not_a_code_change(monkeypatch):
    monkeypatch.setattr(get_settings(), "open_archive_tenants", "kebbi, Ghana ,ghana")
    assert oa.active_tenants() == ["kebbi", "ghana"]
    assert "ghana" not in oa.held_tenants()


def test_an_unknown_tenant_is_ignored_and_reported(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(get_settings(), "open_archive_tenants", "kebbi,atlantis")
    assert oa.active_tenants() == ["kebbi"]
    assert "atlantis" in caplog.text


def test_an_item_dated_by_a_range_is_not_dropped():
    """ESA WorldCover and JRC surface water carry a null `datetime` and a
    start/end pair. Requiring a plain datetime made those collections come
    back empty, as though the area were not covered at all."""
    scene = oa._parse_scene({
        "id": "ESA_WorldCover_10m_2021_v200_N12E006",
        "collection": "esa-worldcover",
        "properties": {"datetime": None, "start_datetime": "2021-01-01T00:00:00Z"},
        "assets": {"map": {"href": "https://example.invalid/map.tif"}},
    })
    assert scene is not None
    assert scene.datetime.year == 2021
    assert scene.assets["map"].endswith("map.tif")
