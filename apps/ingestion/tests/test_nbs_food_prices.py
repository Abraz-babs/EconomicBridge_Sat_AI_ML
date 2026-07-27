"""Unit tests for sources/nbs_food_prices.py.

No network (CLAUDE.md §11) — workbooks are built in-memory. What these pin is
the honesty of the parse, because every failure mode here is SILENT:

  * a unit guessed instead of skipped writes a wrong price with no error;
  * a shifted column writes another zone's price under our zone's name;
  * a renamed sheet or missing zone yields a partial table that still looks
    plausible.

So the parser must raise on layout drift and skip anything it cannot convert
with a stated basis.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from sources.nbs_food_prices import (
    UNIT_BASIS,
    ZONE_BY_TENANT,
    NbsSchemaError,
    _month_end,
    month_urls,
    parse_workbook,
)

ZONES = ["NORTH CENTRAL", "NORTH EAST", "NORTH WEST",
         "SOUTH EAST", "SOUTH SOUTH", "SOUTH WEST"]


def _xlsx(rows: list[tuple[str, list[float]]], *, sheet_name: str = "ZONE all item",
          zones: list[str] | None = None) -> bytes:
    """Minimal but real OOXML workbook: one ZONE sheet, shared strings."""
    zones = zones if zones is not None else ZONES
    strings: list[str] = [*zones, *(label for label, _ in rows), "Item Labels"]
    idx = {s: i for i, s in enumerate(strings)}

    def col(n: int) -> str:
        return chr(ord("A") + n)

    cells = [f'<c r="A1" t="s"><v>{idx["Item Labels"]}</v></c>']
    for i, z in enumerate(zones):
        cells.append(f'<c r="{col(i + 1)}1" t="s"><v>{idx[z]}</v></c>')
    body = ["<row r=\"1\">" + "".join(cells) + "</row>"]
    for r, (label, values) in enumerate(rows, start=2):
        cs = [f'<c r="A{r}" t="s"><v>{idx[label]}</v></c>']
        for i, v in enumerate(values):
            cs.append(f'<c r="{col(i + 1)}{r}"><v>{v}</v></c>')
        body.append(f'<row r="{r}">' + "".join(cs) + "</row>")

    sheet = (
        '<?xml version="1.0"?><worksheet><sheetData>'
        + "".join(body) + "</sheetData></worksheet>"
    )
    shared = (
        '<?xml version="1.0"?><sst count="%d">' % len(strings)
        + "".join(f"<si><t>{s}</t></si>" for s in strings)
        + "</sst>"
    )
    wb = (
        '<?xml version="1.0"?><workbook><sheets>'
        f'<sheet name="Selected Food" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{sheet_name}" sheetId="2" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/worksheets/sheet2.xml", sheet)
    return buf.getvalue()


OBS = date(2024, 10, 31)


# ─── units: convert only on a stated basis, otherwise skip ────────────────


def test_loose_items_are_taken_as_per_kg() -> None:
    data = _xlsx([("Maize grain white sold loose", [900, 800, 700, 950, 1000, 1100])])
    rows = parse_workbook(data, OBS)
    nw = next(r for r in rows if r.zone == "NORTH WEST")
    assert nw.crop == "maize"                  # base name, not maize_white
    assert nw.price_ngn_per_kg == 700.0        # NBS "sold loose" is per kg


def test_pack_weight_multiplier_mechanism_still_works(monkeypatch) -> None:
    """No CURRENT item needs a multiplier — every mapped crop is sold loose —
    but the mechanism must keep working for the next packaged staple, and it
    must take the weight from the LABEL rather than an assumption. Patched in
    rather than kept as a live mapping so the shipped vocabulary stays exactly
    the operator's base-name list."""
    import sources.nbs_food_prices as mod

    monkeypatch.setitem(mod.UNIT_BASIS, "bread sliced 500g", ("bread", 2.0))
    data = _xlsx([("Bread sliced 500g", [1000, 1000, 1500, 1000, 1000, 1000])])
    rows = {(r.crop, r.zone): r.price_ngn_per_kg for r in parse_workbook(data, OBS)}
    assert rows[("bread", "NORTH WEST")] == 3000.0            # 1500 * 2


def test_items_with_no_mass_basis_are_skipped_not_guessed() -> None:
    """Eggs are priced "per one" and oil "1 bottle, specify bottle" — the
    volume is never stated. Inventing one would write a confident wrong price,
    so these must produce no row at all."""
    data = _xlsx([
        ("Agric eggs(medium size price of one)", [200, 200, 200, 200, 200, 200]),
        ("Palm oil: 1 bottle,specify bottle", [2000, 2000, 2000, 2000, 2000, 2000]),
        ("Maize grain white sold loose", [900, 800, 700, 950, 1000, 1100]),
    ])
    rows = parse_workbook(data, OBS)
    assert {r.crop for r in rows} == {"maize"}


def test_unknown_item_is_skipped_without_failing_the_run() -> None:
    data = _xlsx([
        ("Some New Staple NBS Just Added", [10, 10, 10, 10, 10, 10]),
        ("Yam tuber", [500, 500, 400, 500, 500, 500]),
    ])
    rows = parse_workbook(data, OBS)
    assert {r.crop for r in rows} == {"yam"}


# ─── layout drift must fail loudly ────────────────────────────────────────


def test_missing_zone_sheet_raises() -> None:
    data = _xlsx([("Yam tuber", [1, 2, 3, 4, 5, 6])], sheet_name="Summary")
    with pytest.raises(NbsSchemaError, match="no ZONE sheet"):
        parse_workbook(data, OBS)


def test_missing_a_zone_we_depend_on_raises() -> None:
    """Dropping NORTH WEST must not silently yield a table covering only the
    other pilots — three tenants would just go quiet."""
    zones = [z for z in ZONES if z != "NORTH WEST"]
    data = _xlsx([("Yam tuber", [1, 2, 3, 4, 5])], zones=zones)
    with pytest.raises(NbsSchemaError, match="NORTH WEST"):
        parse_workbook(data, OBS)


def test_workbook_with_no_mappable_items_raises() -> None:
    """A wholesale relabel would otherwise return an empty list, which reads
    downstream as 'no price change this month'."""
    data = _xlsx([("Totally Renamed Item", [1, 2, 3, 4, 5, 6])])
    with pytest.raises(NbsSchemaError, match="no usable prices"):
        parse_workbook(data, OBS)


def test_non_xlsx_payload_raises() -> None:
    with pytest.raises(NbsSchemaError, match="not a readable xlsx"):
        parse_workbook(b"<html>404</html>", OBS)


# ─── zone mapping + dates ─────────────────────────────────────────────────


def test_every_nigerian_pilot_maps_to_a_zone_present_in_the_sheet() -> None:
    assert set(ZONE_BY_TENANT.values()) <= set(ZONES)
    for tenant in ("kebbi", "kaduna", "zamfara", "niger", "benue",
                   "plateau", "nasarawa", "fct"):
        assert tenant in ZONE_BY_TENANT


def test_zone_granularity_is_shared_not_per_state() -> None:
    """Kebbi and Zamfara are both NORTH WEST, so NBS gives them the SAME
    number. That is the source's limit; rows must never be presented as a
    state-specific price."""
    assert ZONE_BY_TENANT["kebbi"] == ZONE_BY_TENANT["zamfara"] == "NORTH WEST"
    assert ZONE_BY_TENANT["benue"] == ZONE_BY_TENANT["fct"] == "NORTH CENTRAL"


def test_month_end_handles_leap_years_and_december() -> None:
    assert _month_end(date(2024, 2, 9)) == date(2024, 2, 29)
    assert _month_end(date(2025, 2, 9)) == date(2025, 2, 28)
    assert _month_end(date(2024, 12, 3)) == date(2024, 12, 31)
    assert _month_end(date(2024, 10, 15)) == date(2024, 10, 31)


def test_month_urls_try_both_abbreviated_and_full_names() -> None:
    urls = month_urls(date(2024, 10, 1))
    assert any("selected_food_oct_2024.xlsx" in u for u in urls)
    assert any("selected_food_october_2024.xlsx" in u for u in urls)


def test_unit_basis_multipliers_are_sane() -> None:
    """Every mapping must state a positive multiplier; a zero or negative one
    would silently zero out or invert a price."""
    for label, (crop, mult) in UNIT_BASIS.items():
        assert crop and mult > 0, label
