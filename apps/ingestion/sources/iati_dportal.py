"""IATI aid activities via d-portal — Module 02 (Aid Coordination).

IATI (the International Aid Transparency Initiative) is the open standard in
which donors, UN agencies and NGOs publish their OWN activities: who funds and
runs what, in which sectors, between which dates and — for a share of them —
where. d-portal (d-portal.org, run for the IATI Secretariat) serves the whole
IATI corpus through a keyless query API, which is all this module reads.

Why IATI: HDX HAPI's operational presence, the first source wired in, covers
only north-east Nigeria (Borno, Yobe, Adamawa) — re-checked 2026-09-25, still
0 rows for every pilot state. IATI had located, current activities in all
eight Nigerian pilots, Ghana and Senegal the same day.

WHAT COUNTS AS "WHERE"
----------------------
A published location is often not a site. Publishers pin programme-level
activities to a state or national centre, and the precision field does not
separate them (plain "Zamfara" arrives marked exact). Measured 2026-09-25: one
Zamfara coordinate carried 232 activities, central Abuja 224+142+96, Nigeria's
centre points 117 and 75. So each location is classified:

  national  — the country, Abuja head-office pins, Nigeria's centre points.
              Dropped for a state (a national programme is not activity IN the
              state); counted country-wide for the Ghana / Senegal tenants.
  states    — a state label ("Kebbi State", "NG - Adamawa-Bauchi-Kebbi"):
              statewide activity for each pilot state it names.
  area      — a coordinate shared by many activities lying near the state's
              own centre: a state-centre pin, statewide.
  site      — everything else: a real place, counted in the LGA containing it.
              Busy LGA-headquarters pins (UNICEF files dozens of outputs at
              Zurmi, Zuru) stay sites — they are LGA-level, which is the point.

WHAT COUNTS AS "CURRENT"
------------------------
Status fields go stale (a 2011 project still marked "implementation"), so an
activity is current only when today falls between its start and end dates; one
with no end date counts for OPEN_ENDED_YEARS after it started. AidData is
excluded: it republishes other donors' historical projects with geocodes, and
its statuses are not maintained.

Licensing: IATI data is published by each organisation under an open licence
it declares (overwhelmingly CC BY / ODC / public domain). Attribution: "IATI
data, via d-portal.org".
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

log = logging.getLogger(__name__)

DPORTAL_URL = "https://d-portal.org/q.json"
ATTRIBUTION = "IATI data, via d-portal.org"

# Activities with no end date count as current for this long after starting.
OPEN_ENDED_YEARS = 5
# A coordinate carrying at least this many activities is a candidate centre pin.
SHARED_MIN = 10
# ...and is a STATE-centre pin when it lies this close to the state's centre.
STATE_CENTRE_KM = 30.0
# Central Abuja: busy pins here are head offices of national programmes.
ABUJA_CENTRE = (7.49, 9.06)
ABUJA_KM = 15.0
# Gazetteer centre points for "Nigeria" seen in the corpus.
NATIONAL_POINTS: tuple[tuple[float, float], ...] = ((8.0, 10.0), (8.675, 9.082), (8.0, 9.6))
NATIONAL_POINT_KM = 2.0

# Publishers left out — see module docstring.
EXCLUDED_REPORTERS = frozenset({"US-501c3-522318905"})   # AidData

COUNTRY_NAMES = frozenset({
    "nigeria", "federal republic of nigeria", "ghana", "republic of ghana",
    "senegal", "republic of senegal", "abuja", "nigeria abuja", "abuja nigeria",
})

NIGERIAN_STATES: tuple[str, ...] = (
    "abia", "adamawa", "akwa ibom", "anambra", "bauchi", "bayelsa", "benue",
    "borno", "cross river", "delta", "ebonyi", "edo", "ekiti", "enugu", "gombe",
    "imo", "jigawa", "kaduna", "kano", "katsina", "kebbi", "kogi", "kwara",
    "lagos", "nasarawa", "niger", "ogun", "ondo", "osun", "oyo", "plateau",
    "rivers", "sokoto", "taraba", "yobe", "zamfara", "federal capital territory",
    "fct",
)
_STATE_ALIASES = {"nassarawa": "nasarawa", "federal capital territory": "fct"}
_LABEL_NOISE = frozenset({"state", "states", "ng", "nigeria", "and", "of", "the", "region", "regions"})

# Pilot tenants that are one Nigerian state, by the state's name above.
TENANT_STATE: dict[str, str] = {
    "kebbi": "kebbi", "zamfara": "zamfara", "kaduna": "kaduna", "niger": "niger",
    "plateau": "plateau", "nasarawa": "nasarawa", "benue": "benue", "fct": "fct",
}
# Pilot tenants that are a whole country (national activity = country-wide).
TENANT_COUNTRY: dict[str, str] = {**{t: "NG" for t in TENANT_STATE}, "ghana": "GH", "senegal": "SN"}
COUNTRY_TENANTS = frozenset({"ghana", "senegal"})

# OECD DAC 3-digit sector groups → (display name, overlap bucket). Two
# organisations "overlap" in an LGA when they share a bucket there.
DAC_GROUPS: dict[str, tuple[str, str]] = {
    "110": ("Education", "Education"), "111": ("Education", "Education"),
    "112": ("Basic education", "Education"), "113": ("Secondary education", "Education"),
    "114": ("Post-secondary education", "Education"),
    "120": ("Health", "Health"), "121": ("Health", "Health"), "122": ("Basic health", "Health"),
    "123": ("Non-communicable diseases", "Health"),
    "130": ("Population & reproductive health", "Health"),
    "140": ("Water & sanitation", "Water & sanitation"),
    "150": ("Government & civil society", "Governance & peace"),
    "151": ("Government & civil society", "Governance & peace"),
    "152": ("Conflict, peace & security", "Governance & peace"),
    "160": ("Social protection & services", "Social protection"),
    "210": ("Transport", "Infrastructure"), "220": ("Communications", "Infrastructure"),
    "230": ("Energy", "Energy"), "231": ("Energy policy", "Energy"),
    "232": ("Renewable energy", "Energy"), "233": ("Energy", "Energy"),
    "234": ("Energy", "Energy"), "235": ("Energy", "Energy"), "236": ("Energy distribution", "Energy"),
    "240": ("Banking & finance", "Economy & jobs"), "250": ("Business", "Economy & jobs"),
    "310": ("Agriculture", "Agriculture & food"), "311": ("Agriculture", "Agriculture & food"),
    "312": ("Forestry", "Agriculture & food"), "313": ("Fishing", "Agriculture & food"),
    "320": ("Industry", "Economy & jobs"), "321": ("Industry", "Economy & jobs"),
    "322": ("Mining", "Economy & jobs"), "323": ("Construction", "Economy & jobs"),
    "330": ("Trade", "Economy & jobs"), "331": ("Trade", "Economy & jobs"),
    "332": ("Tourism", "Economy & jobs"),
    "410": ("Environment", "Environment"), "430": ("Multisector", "Multisector"),
    "510": ("Budget support", "Budget support"),
    "520": ("Food assistance", "Agriculture & food"), "530": ("Commodity assistance", "Agriculture & food"),
    "720": ("Emergency response", "Emergency response"),
    "730": ("Reconstruction & recovery", "Emergency response"),
    "740": ("Disaster preparedness", "Emergency response"),
}


@dataclass(frozen=True, slots=True)
class IatiLocation:
    """One published location of one IATI activity."""

    iati_id: str
    org_name: str
    org_ref: str | None
    title: str | None
    sector_groups: tuple[str, ...]
    start: date | None
    end: date | None
    lon: float
    lat: float
    location_name: str | None
    shared: int          # activities published at this same coordinate


class DPortalError(RuntimeError):
    """Non-200 or malformed body from d-portal."""


# ─── pure rules ──────────────────────────────────────────────────────────


def day(n: int | None) -> date | None:
    """d-portal dates are whole days since 1970-01-01."""
    return date(1970, 1, 1) + timedelta(days=int(n)) if n not in (None, 0) else None


def is_current(start: date | None, end: date | None, today: date) -> bool:
    if start is not None and start > today:
        return False
    if end is not None:
        return end >= today
    if start is None:
        return False
    return start >= today - timedelta(days=365 * OPEN_ENDED_YEARS)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2)),
                      (a[1] - b[1]) * 110.57)


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z]+", " ", (name or "").lower()).strip()


def named_states(name: str | None) -> frozenset[str]:
    """The Nigerian states a location name is a LABEL for — or empty.

    "Kebbi State" → {kebbi}; "NG - Adamawa-Bauchi-Kebbi" → {adamawa, bauchi,
    kebbi}; "Argungu" → {} (a place). A name only counts as a label when
    nothing but state names and filler words remain, so a village called
    "Kaduna Road" or "Jos Plateau Clinic" stays a place.
    """
    n = f" {_norm(name)} "
    # "Niger Delta" is a region of the south, not Niger State (and not Delta).
    if not n.strip() or " niger delta " in n:
        return frozenset()
    found = set()
    for s in sorted(NIGERIAN_STATES, key=len, reverse=True):
        if f" {s} " in n:
            found.add(_STATE_ALIASES.get(s, s))
            n = n.replace(f" {s} ", " ")
    for a, s in _STATE_ALIASES.items():
        if f" {a} " in n:
            found.add(s)
            n = n.replace(f" {a} ", " ")
    rest = [w for w in n.split() if w not in _LABEL_NOISE]
    return frozenset(found) if found and not rest else frozenset()


def is_national(loc: IatiLocation) -> bool:
    n = _norm(loc.location_name)
    if n in COUNTRY_NAMES:
        return True
    if any(km((loc.lon, loc.lat), p) <= NATIONAL_POINT_KM for p in NATIONAL_POINTS):
        return True
    return loc.shared >= SHARED_MIN and km((loc.lon, loc.lat), ABUJA_CENTRE) <= ABUJA_KM


def sector_names(groups: tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for g in groups:
        name = DAC_GROUPS.get(g, ("Other", "Other"))[0]
        if name not in seen:
            seen.append(name)
    return seen


def sector_buckets(groups: tuple[str, ...]) -> list[str]:
    return sorted({DAC_GROUPS.get(g, ("Other", "Other"))[1] for g in groups}) or ["Other"]


# ─── fetch ───────────────────────────────────────────────────────────────


class DPortalClient:
    """Keyless reader for active IATI activities of one recipient country."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def _query(self, client: httpx.AsyncClient, params: dict[str, str]) -> list[dict]:
        resp = await client.get(DPORTAL_URL, params={**params, "limit": "-1"},
                                timeout=180.0, follow_redirects=True)
        if resp.status_code != 200:
            raise DPortalError(f"d-portal {resp.status_code}: {resp.text[:200]}")
        try:
            rows = resp.json().get("rows")
        except ValueError as exc:
            raise DPortalError(f"d-portal: non-JSON body: {resp.text[:200]}") from exc
        if not isinstance(rows, list):
            raise DPortalError("d-portal: no rows array")
        return rows

    async def fetch_country(self, country_code: str) -> list[IatiLocation]:
        """Every published location of every activity in implementation."""
        base = {"country_code": country_code, "status_code": "2"}
        client = self._http or httpx.AsyncClient()
        try:
            acts = await self._query(client, {**base, "from": "act",
                                              "select": "aid,title,reporting,reporting_ref,day_start,day_end"})
            locs = await self._query(client, {**base, "from": "act,location",
                                              "select": "aid,location_name,location_longitude,location_latitude"})
            secs = await self._query(client, {**base, "from": "act,sector",
                                              "select": "aid,sector_group"})
        finally:
            if self._http is None:
                await client.aclose()
        return assemble(acts, locs, secs)


def assemble(acts: list[dict], locs: list[dict], secs: list[dict]) -> list[IatiLocation]:
    """Join d-portal's three result sets into one row per activity location."""
    by_aid = {a["aid"]: a for a in acts if a.get("aid")}
    groups: dict[str, set[str]] = defaultdict(set)
    for s in secs:
        if s.get("aid") and s.get("sector_group"):
            groups[s["aid"]].add(str(s["sector_group"]))
    points: list[tuple[str, float, float, str | None]] = []
    for r in locs:
        try:
            lon, lat = float(r["location_longitude"]), float(r["location_latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if r.get("aid") in by_aid and -180 <= lon <= 180 and -90 <= lat <= 90:
            points.append((r["aid"], lon, lat, (r.get("location_name") or "").strip() or None))
    shared = Counter((round(lon, 3), round(lat, 3)) for _, lon, lat, _ in points)
    out: list[IatiLocation] = []
    seen: set[tuple[str, float, float]] = set()
    for aid, lon, lat, name in points:
        a = by_aid[aid]
        if a.get("reporting_ref") in EXCLUDED_REPORTERS or (aid, lon, lat) in seen:
            continue
        seen.add((aid, lon, lat))
        out.append(IatiLocation(
            iati_id=aid,
            org_name=(a.get("reporting") or a.get("reporting_ref") or "Unknown").strip()[:200],
            org_ref=a.get("reporting_ref"),
            title=(a.get("title") or "").strip()[:500] or None,
            sector_groups=tuple(sorted(groups.get(aid, ()))),
            start=day(a.get("day_start")),
            end=day(a.get("day_end")),
            lon=lon, lat=lat, location_name=name,
            shared=shared[(round(lon, 3), round(lat, 3))],
        ))
    return out
