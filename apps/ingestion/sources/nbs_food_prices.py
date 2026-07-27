"""NBS "Selected Food Prices Watch" — the national monthly food-price source.

Nigeria's National Bureau of Statistics publishes a monthly food-price watch as
a small XLSX (not only PDF, which is what makes this tractable):

    https://nigerianstat.gov.ng/resource/selected_food_{mon}_{yyyy}.xlsx

WHAT IT ACTUALLY CONTAINS — read this before trusting a number
--------------------------------------------------------------
  sheet 1  per-commodity NATIONAL average, with MoM / YoY and only the
           highest/lowest STATE annotated (e.g. "Bauchi (3450)")
  sheet 2  per-commodity by the six GEOPOLITICAL ZONES

There is **no state x commodity matrix**. So the finest honest granularity for
a given pilot is its ZONE, and our eight Nigerian pilots collapse into two:

    NORTH WEST     kebbi, kaduna, zamfara
    NORTH CENTRAL  niger, benue, plateau, nasarawa, fct

Kebbi and Zamfara therefore carry identical NBS numbers. That is a property of
the source, not a bug, and rows are tagged `nbs_zone_v1` so nothing downstream
can present a zone average as a state or LGA price.

UNITS — where a careless parser would go quietly wrong
------------------------------------------------------
The target column is `price_ngn_per_kg`, but NBS quotes mixed units: some items
are sold loose (per kg by NBS convention), some are a fixed pack whose weight is
stated in the label ("Bread sliced 500g", "Wheat flour ... 2kg"), and some are
not mass at all ("price of one" egg, "1 bottle, specify bottle" — an unstated
volume).

We therefore convert ONLY where the basis is explicit, and SKIP the rest. We do
not invent a bottle volume or an egg weight to make a row fit the column. An
unmapped item is skipped loudly (counted and logged), never guessed — see
UNIT_BASIS and `parse_workbook`.

SCHEMA DRIFT
------------
NBS reformats between releases. `parse_workbook` validates the sheet layout it
depends on and raises NbsSchemaError rather than returning partial or shifted
data, so a layout change fails the ingest visibly instead of writing silently
wrong prices.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://nigerianstat.gov.ng/resource"
SOURCE_TAG = "nbs_zone_v1"

# The six NBS geopolitical zones, and which pilots sit in each. Only the zones
# containing pilots are consumed; the rest are parsed but unused.
ZONE_BY_TENANT: dict[str, str] = {
    "kebbi": "NORTH WEST",
    "kaduna": "NORTH WEST",
    "zamfara": "NORTH WEST",
    "niger": "NORTH CENTRAL",
    "benue": "NORTH CENTRAL",
    "plateau": "NORTH CENTRAL",
    "nasarawa": "NORTH CENTRAL",
    "fct": "NORTH CENTRAL",
}

# NBS item label -> (crop, kg multiplier applied to the quoted price).
#
# ONE REFERENCE VARIETY PER CROP — see the same note in sources/fews_prices.py.
# NBS lists white AND yellow maize, local AND imported rice, brown AND white
# beans; taking both would write two different prices for one crop/region/month.
# The dominant food variety wins and the rest are not ingested.
#
# multiplier semantics: price_per_kg = quoted_price * multiplier
#   1.0  quoted per kg already ("sold loose" is NBS's per-kg convention)
#   2.0  quoted for a 500 g pack
#   0.5  quoted for a 2 kg pack
# An item absent from this map is SKIPPED, not guessed. Eggs ("price of one"),
# bottles ("specify bottle" — volume never stated) and per-item fish have no
# defensible mass basis and are deliberately absent.
UNIT_BASIS: dict[str, tuple[str, float]] = {
    "maize grain white sold loose": ("maize", 1.0),
    "rice local sold loose": ("rice", 1.0),
    "beans brown,sold loose": ("cowpea", 1.0),
    "gari white,sold loose": ("cassava", 1.0),
    "yam tuber": ("yam", 1.0),
    "sweet potato": ("sweet_potato", 1.0),
    "onion bulb": ("onion", 1.0),
    "tomato": ("tomato", 1.0),
    "plantain(unripe)": ("plantain", 1.0),
}


class NbsSchemaError(RuntimeError):
    """The workbook no longer matches the layout we parse."""


class NbsFetchError(RuntimeError):
    """The monthly workbook could not be retrieved."""


@dataclass(frozen=True)
class ZonePrice:
    """One commodity's average price for one zone, in a given month."""

    crop: str
    zone: str
    observed_at: date
    price_ngn_per_kg: float
    nbs_label: str


def month_urls(when: date) -> list[str]:
    """Candidate URLs for a month. NBS is inconsistent about abbreviating the
    month, so try both forms rather than assuming one."""
    full = when.strftime("%B").lower()
    abbr = when.strftime("%b").lower()
    names = [abbr] if abbr == full else [abbr, full]
    return [f"{BASE_URL}/selected_food_{n}_{when.year}.xlsx" for n in names]


def _read_cells(zf: zipfile.ZipFile, sheet_path: str) -> dict[str, str]:
    """Cell values from a worksheet, resolving the shared-string table.

    Parsed straight from the OOXML rather than via openpyxl to keep the
    ingestion image free of another dependency; the format we need is small:
    <c r="A1" t="s"><v>7</v></c> where t="s" means <v> indexes sharedStrings,
    and t="inlineStr" carries the text inline instead.
    """
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        raw = zf.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        shared = [
            re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", raw, re.S)
        ]

    body = zf.read(sheet_path).decode("utf-8", "replace")
    cells: dict[str, str] = {}
    for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*)>(.*?)</c>', body, re.S):
        ref, attrs, inner = m.groups()
        if 't="inlineStr"' in attrs:
            text = re.findall(r"<t[^>]*>(.*?)</t>", inner, re.S)
            if text:
                cells[ref] = re.sub(r"<[^>]+>", "", text[0]).strip()
            continue
        val = re.search(r"<v>(.*?)</v>", inner, re.S)
        if not val:
            continue
        raw_v = val.group(1)
        if 't="s"' in attrs:
            try:
                raw_v = shared[int(raw_v)]
            except (ValueError, IndexError):
                pass
        cells[ref] = raw_v.strip()
    return cells


def _col(ref: str) -> str:
    return re.sub(r"\d", "", ref)


def _row(ref: str) -> int:
    return int(re.sub(r"[A-Z]", "", ref))


def parse_workbook(content: bytes, observed_at: date) -> list[ZonePrice]:
    """Zone-level prices from the workbook, or raise on unexpected layout.

    Reads the ZONE sheet: row 1 is the zone header, column A the item label.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise NbsSchemaError(f"not a readable xlsx: {exc}") from exc

    wb = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    names = re.findall(r'<sheet name="([^"]+)"', wb)
    zone_idx = next(
        (i for i, n in enumerate(names, start=1) if "zone" in n.lower()), None
    )
    if zone_idx is None:
        raise NbsSchemaError(
            f"no ZONE sheet in workbook; sheets={names}. NBS changed the layout "
            "— check the release before trusting any parsed price."
        )

    cells = _read_cells(zf, f"xl/worksheets/sheet{zone_idx}.xml")
    if not cells:
        raise NbsSchemaError("ZONE sheet parsed to zero cells")

    # Header row: map each zone name to its column.
    zone_col: dict[str, str] = {}
    for ref, val in cells.items():
        if _row(ref) == 1 and val.strip().upper() in {
            "NORTH CENTRAL", "NORTH EAST", "NORTH WEST",
            "SOUTH EAST", "SOUTH SOUTH", "SOUTH WEST",
        }:
            zone_col[val.strip().upper()] = _col(ref)
    needed = set(ZONE_BY_TENANT.values())
    missing = needed - set(zone_col)
    if missing:
        raise NbsSchemaError(
            f"ZONE sheet is missing the zones we need: {sorted(missing)}; "
            f"found {sorted(zone_col)}"
        )

    out: list[ZonePrice] = []
    skipped: list[str] = []
    for ref, label in cells.items():
        if _col(ref) != "A" or _row(ref) == 1:
            continue
        key = label.strip().lower()
        mapped = UNIT_BASIS.get(key)
        if mapped is None:
            if key:
                skipped.append(label.strip())
            continue
        crop, multiplier = mapped
        for zone in needed:
            raw = cells.get(f"{zone_col[zone]}{_row(ref)}")
            if raw in (None, ""):
                continue
            try:
                price = float(raw)
            except ValueError:
                continue
            if price <= 0:
                continue
            out.append(ZonePrice(
                crop=crop,
                zone=zone,
                observed_at=observed_at,
                price_ngn_per_kg=round(price * multiplier, 2),
                nbs_label=label.strip(),
            ))

    if not out:
        raise NbsSchemaError(
            "ZONE sheet yielded no usable prices — layout or item labels "
            f"changed. Unmapped labels seen: {skipped[:8]}"
        )
    if skipped:
        # Not an error: eggs/bottles have no defensible mass basis. Logged so a
        # newly-added staple is noticed rather than silently dropped forever.
        log.info(
            "nbs: skipped %d item(s) with no per-kg basis: %s",
            len(skipped), ", ".join(sorted(set(skipped))[:6]),
        )
    return out


class NbsFoodPriceClient:
    """Fetches and parses one month of the NBS food-price watch."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    def _ctx(self):
        if self._http is not None:
            from sources.copernicus import _Borrowed
            return _Borrowed(self._http)
        # NBS rejects non-browser agents with 406.
        return httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                "Accept": "*/*",
            },
        )

    async def fetch_month(self, when: date) -> list[ZonePrice]:
        """Zone prices for `when`'s month. Empty when NBS has not published it
        yet (normal — the watch lags the month it reports on)."""
        last_status: int | None = None
        async with self._ctx() as client:
            for url in month_urls(when):
                resp = await client.get(url)
                last_status = resp.status_code
                if resp.status_code == 200 and resp.content[:2] == b"PK":
                    return parse_workbook(resp.content, _month_end(when))
                if resp.status_code not in (403, 404):
                    raise NbsFetchError(f"NBS {resp.status_code} for {url}")
        log.info("nbs: no workbook published for %s (last status %s)",
                 when.strftime("%Y-%m"), last_status)
        return []


def _month_end(when: date) -> date:
    """The month's LAST day, matching how FEWS NET stamps `period_date` so both
    sources land on the same observed_at and can be compared per month."""
    if when.month == 12:
        return date(when.year, 12, 31)
    first_of_next = date(when.year, when.month + 1, 1)
    return date.fromordinal(first_of_next.toordinal() - 1)
