"""Open Sentinel archive — catalogue search, URL signing, tenant gating.

WHY THIS EXISTS
---------------
The per-LGA sweeps read Sentinel through Copernicus's metered Statistical API,
one 3 x 3 km box at each LGA centroid. Measured on 2026-09-15 against the real
LGA boundaries, that watches 4,023 km2 of the 715,731 km2 the 447 pilot LGAs
cover: 0.56%. Enlarging the box cannot fix it. The API returns one AVERAGE per
box, so a 50 ha clearing averaged into a 1,200 km2 LGA disappears — and whole
LGAs would cost ~178x the Processing Units anyway.

This finds the same Sentinel data in the open archive and signs it for reading;
sources/cog_window reads it as whole-LGA image windows with no PU meter. It is
the foundation for pixel-level change detection and detects nothing itself.

MEASURED 2026-09-15, from eu-west-1 Fargate (the production network)
  whole 36 km LGA window, native 10 m : 3.7 s radar, 3.9 s optical
  the same window at 30 m             : 1.5 s radar, 2.3 s optical
  Sentinel-1 RTC over every Nigerian pilot: a new pass at least every 4-5 days
  (S1C + S1D, ascending and descending), published 2-4 days after acquisition.
  Sentinel-2 in peak rainy season: 55-93% median cloud, so radar carries the
  wet season and optical corroborates in the dry season.

UNITS — VERIFIED, NOT ASSUMED
  Sentinel-1 RTC assets are LINEAR gamma-naught (asset tag Scale=linear,
  SARPixelContent=intensity), float32, nodata -32768. Over Jega the median was
  0.092, i.e. -10.4 dB. The existing Copernicus sweeps store dB, so radar from
  here must go through cog_window.to_db() before it meets that history.

DESIGN RULES
------------
* STAC-generic. Planetary Computer is the default; Earth Search or CDSE work by
  changing config.open_archive_stac_url + open_archive_signing. A free service
  with no SLA must be replaceable without a code change.
* Radar is only comparable within one orbit geometry (Scene.orbit_key). Mixing
  orbits is what made one Kebbi pass read 1.5-3 dB brighter every 12 days and
  pose as land change.
* Signing tokens are cached until shortly before expiry and are NEVER logged.
* Only config.open_archive_tenants may consume reads. Ghana and Senegal ship
  configured but held.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import get_settings
from sources import lga_boundaries

log = logging.getLogger(__name__)

S1_RTC = "sentinel-1-rtc"
S2_L2A = "sentinel-2-l2a"

# A page ceiling so a misbehaving catalogue cannot loop forever. Hitting it is
# logged: silently truncating a scene list reads as "covered everything".
MAX_PAGES = 20
PAGE_LIMIT = 1000

# Refresh a signing token this long before its stated expiry, so a long read
# never starts on a token that dies halfway through.
TOKEN_SKEW_S = 300.0

_TOKENS: dict[str, tuple[str, float]] = {}   # collection -> (token, valid_until)
# One refresh at a time per collection. Whole-LGA scans read many assets at
# once, so without this every concurrent reader misses the cache together and
# stampedes the signing endpoint — measured as 8 token requests in 100 ms
# against a free service with no SLA.
_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}


class OpenArchiveError(RuntimeError):
    """The catalogue or signing endpoint failed or answered nonsense."""


@dataclass(frozen=True, slots=True)
class Scene:
    """One catalogue item: a single satellite acquisition."""

    id: str
    collection: str
    datetime: datetime
    assets: dict[str, str]            # asset key -> unsigned href
    orbit_state: str | None = None    # Sentinel-1: ascending / descending
    relative_orbit: int | None = None
    platform: str | None = None
    cloud_cover: float | None = None  # Sentinel-2

    @property
    def orbit_key(self) -> str | None:
        """Same-geometry key. Radar may only be compared within one key."""
        if self.orbit_state is None or self.relative_orbit is None:
            return None
        return f"{self.orbit_state}:{self.relative_orbit}"


def _utc(d: datetime) -> str:
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_scene(feature: dict) -> Scene | None:
    p = feature.get("properties") or {}
    if not p.get("datetime") or not feature.get("id"):
        return None
    ro, cc = p.get("sat:relative_orbit"), p.get("eo:cloud_cover")
    return Scene(
        id=str(feature["id"]),
        collection=str(feature.get("collection") or ""),
        datetime=datetime.fromisoformat(str(p["datetime"]).replace("Z", "+00:00")),
        assets={k: v["href"] for k, v in (feature.get("assets") or {}).items()
                if isinstance(v, dict) and v.get("href")},
        orbit_state=p.get("sat:orbit_state"),
        relative_orbit=int(ro) if ro is not None else None,
        platform=p.get("platform"),
        cloud_cover=float(cc) if cc is not None else None,
    )


async def search(
    collection: str,
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    *,
    query: dict | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Scene]:
    """Every scene of `collection` intersecting `bbox` in [start, end], oldest first."""
    url = get_settings().open_archive_stac_url.rstrip("/") + "/search"
    body: dict = {"collections": [collection], "bbox": list(bbox),
                  "datetime": f"{_utc(start)}/{_utc(end)}", "limit": PAGE_LIMIT}
    if query:
        body["query"] = query
    method = "POST"
    raw: list[dict] = []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0))
    try:
        for _ in range(MAX_PAGES):
            resp = (await client.post(url, json=body) if method == "POST"
                    else await client.get(url))
            resp.raise_for_status()
            page = resp.json()
            raw.extend(page.get("features") or [])
            nxt = next((link for link in page.get("links") or []
                        if link.get("rel") == "next"), None)
            if not nxt:
                break
            url, method = nxt["href"], str(nxt.get("method") or "GET").upper()
            body = nxt.get("body") or body
        else:
            log.warning("open_archive: %s search truncated at %d pages (%d scenes) — "
                        "later scenes were NOT listed", collection, MAX_PAGES, len(raw))
    except (httpx.HTTPError, ValueError) as exc:
        raise OpenArchiveError(f"STAC search failed for {collection}: {exc}") from exc
    finally:
        if owns:
            await client.aclose()

    scenes: dict[str, Scene] = {}
    for f in raw:
        s = _parse_scene(f)
        if s is not None:
            scenes.setdefault(s.id, s)
    return sorted(scenes.values(), key=lambda s: s.datetime)


async def _token(collection: str, client: httpx.AsyncClient | None) -> str:
    hit = _TOKENS.get(collection)
    if hit and hit[1] > time.time():
        return hit[0]
    async with _TOKEN_LOCKS.setdefault(collection, asyncio.Lock()):
        # Re-check: whoever held the lock has probably just refreshed it.
        hit = _TOKENS.get(collection)
        if hit and hit[1] > time.time():
            return hit[0]
        return await _refresh_token(collection, client)


async def _refresh_token(collection: str, client: httpx.AsyncClient | None) -> str:
    now = time.time()
    url = f"{get_settings().open_archive_sas_url.rstrip('/')}/token/{collection}"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=20.0))
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OpenArchiveError(f"signing failed for {collection}: {exc}") from exc
    finally:
        if owns:
            await client.aclose()
    token, expiry = doc.get("token"), doc.get("msft:expiry")
    if not token:
        raise OpenArchiveError(f"signing endpoint returned no token for {collection}")
    until = now + 600.0
    if expiry:
        try:
            until = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).timestamp() - TOKEN_SKEW_S
        except ValueError:
            pass
    _TOKENS[collection] = (token, until)
    # Collection and expiry only. The token is a credential.
    log.info("open_archive: signing token refreshed collection=%s expiry=%s", collection, expiry)
    return token


async def signed_href(collection: str, href: str, *,
                      client: httpx.AsyncClient | None = None) -> str:
    """An asset URL the reader can open, signed if the catalogue requires it."""
    strategy = get_settings().open_archive_signing
    if strategy == "none":
        return href
    if strategy != "planetary_computer":
        raise OpenArchiveError(f"unknown open_archive_signing {strategy!r}")
    token = await _token(collection, client)
    return href + ("&" if "?" in href else "?") + token


def active_tenants() -> list[str]:
    """Pilots allowed to consume open-archive reads, in configured order.

    Validated against the boundary file: a tenant with no outlines cannot be
    scanned, so a typo is logged and dropped rather than silently producing an
    empty sweep that looks calm.
    """
    configured = set(lga_boundaries.tenants())
    out: list[str] = []
    for raw in get_settings().open_archive_tenants.split(","):
        t = raw.strip().lower()
        if not t or t in out:
            continue
        if t not in configured:
            log.warning("open_archive: tenant %r has no LGA boundaries — ignored", t)
            continue
        out.append(t)
    return out


def held_tenants() -> list[str]:
    """Configured pilots NOT yet consuming reads (Ghana, Senegal by default)."""
    active = set(active_tenants())
    return [t for t in lga_boundaries.tenants() if t not in active]
