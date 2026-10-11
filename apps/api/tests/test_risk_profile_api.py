"""Pre-season risk profile: summary, words, CSV, PDF, and who may see and download it."""
from __future__ import annotations

import asyncio
import csv
import inspect
import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.risk_profile import csv_text, plain_sentences, spearman, summarise
from services.risk_profile_report import RiskReport, render_risk_report


def _square(x: float, y: float, d: float = 0.2) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


def _row(lga: str, x: float, rp10: float, seen24: float, flood: str, drought_years: list[int],
         failed: list[int]) -> dict:
    return {
        "lga": lga, "band_flood": flood, "band_drought": "low", "band_rains": "moderate" if failed else "low",
        "sources": "test sources",
        "figures": {
            "area_km2": 500.0, "cropland_ha": 30000, "cropland_pct": 60.0,
            "flood": {"rp10_crop_pct": rp10, "rp10_crop_ha": int(300 * rp10), "rp100_crop_pct": rp10 + 2,
                      "rp100_crop_ha": int(300 * (rp10 + 2)), "rp100_deep_crop_pct": rp10 / 2,
                      "rp10_area_pct": rp10 / 2, "rp100_area_pct": rp10 / 2 + 1,
                      "mapped": {"2024-09": {"label": "5–9 Sep 2024", "area_pct": seen24, "crop_pct": seen24,
                                             "crop_ha": int(300 * seen24), "cloud_pct": 1.0}}},
            "rain": {"season_months": [5, 6, 7, 8, 9], "normal_mm": 800.0, "cv_pct": 13.0,
                     "totals": {"1991": 800.0}, "drought_seasons": drought_years,
                     "worst": {"year": 2013, "pct_of_normal": 75.0}, "first_year": 1991, "last_year": 2025},
            "rains": {"years": list(range(1998, 2026)), "onset_median": "06-02", "false_starts": failed[:1],
                      "late_onsets": failed[1:2], "long_dry_spells": failed[2:], "failed_seasons": failed},
            "exposure": {"villages": 120, "people": 200000, "under5": 40000},
            "register": [{"type": "flood", "date": "2024-09-01", "name": "2024 rainy-season floods"}],
            "centroid": [x + 0.1, 12.1], "outline": _square(x, 12.0),
        },
    }


ROWS = [
    _row("Suru", 4.0, 33.4, 23.7, "high", [2013], [2002, 2004, 2011]),
    _row("Augie", 4.2, 25.0, 15.0, "high", [2013, 2016, 2017], [2005]),
    _row("Zuru", 4.4, 0.4, 0.1, "low", [2003], []),
    _row("Jega", 4.6, 4.4, 0.8, "moderate", [2013], [2009]),
]


def test_rank_agreement() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert spearman([1, 2], [1, 2]) is None


def test_summary_adds_up() -> None:
    s = summarise(ROWS)
    assert s["lgas"] == 4 and s["cropland_ha"] == 120000
    assert s["bands"]["flood"] == {"high": 2, "moderate": 1, "low": 1, "none": 0}
    assert s["mapped"][0]["lgas_with_water"] == 2
    assert s["mapped"][0]["agreement"] == 1.0
    assert (s["drought_seasons_min"], s["drought_seasons_max"], s["seasons"]) == (1, 3, 35)
    assert (s["rains_failed_min"], s["rains_failed_max"], s["rains_seasons"]) == (0, 3, 28)
    assert s["people"] == 800000


def test_plain_sentences_lead_with_farmland_and_never_quote_accuracy() -> None:
    text = " ".join(plain_sentences("Suru", ROWS[0]["figures"]))
    assert text.startswith("33% of Suru's farmland")
    assert "23.7% of the LGA on 5–9 Sep 2024" in text
    assert "1 of the 35 seasons since 1991" in text
    assert "3 of 28 seasons had a false start" in text and "around 2 June" in text
    for word in ("accuracy", "accurate", "guarantee", "will flood"):
        assert word not in text.lower()
    low = " ".join(plain_sentences("Zuru", ROWS[2]["figures"]))
    assert low.startswith("Almost none of Zuru's farmland")


def test_csv_has_every_lga_and_the_round() -> None:
    body = csv_text(ROWS, 2025, "risk_profile_v1")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert [r["lga"] for r in rows] == ["Augie", "Jega", "Suru", "Zuru"]
    suru = rows[2]
    assert suru["farmland_in_1in10_zone_pct"] == "33.4"
    assert suru["water_2024-09_lga_pct"] == "23.7"
    assert suru["seasons_below_80pct_years"] == "2013"
    assert suru["false_start_years"] == "2002"
    assert suru["through_season"] == "2025" and suru["method"] == "risk_profile_v1"


def test_report_renders() -> None:
    from PIL import Image

    img = Image.new("L", (40, 10), 0)
    img.putpixel((5, 5), 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rep = RiskReport(prepared_for="Test Insurer", reference="RP-T-1", state="Kebbi State", through=2025,
                     method="risk_profile_v1", rows=ROWS, summary=summarise(ROWS),
                     overlays={"rp10_farmland": {"bounds": [4.0, 12.0, 4.8, 12.2], "png": buf.getvalue()}})
    pdf = render_risk_report(rep, generated_at=datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 8_000


def test_viewing_is_for_insurers_and_downloads_for_super_admin() -> None:
    from routers import risk_profile

    assert "require_insurance_viewer" in inspect.getsource(risk_profile.risk_profile)
    assert "require_super_admin" in inspect.getsource(risk_profile.risk_profile_csv)
    assert "require_super_admin" in inspect.getsource(risk_profile.risk_profile_report)


def test_insurer_category_exists_and_holds_no_data() -> None:
    from services.tenant_categories import INSURER_CATEGORY, is_geographic, is_known_category

    assert is_known_category(INSURER_CATEGORY)
    assert not is_geographic(INSURER_CATEGORY)


@pytest.mark.parametrize("role,category,allowed", [
    ("super_admin", None, True),
    ("tenant_admin", "insurer", True),
    ("tenant_admin", "ngo", False),
    ("tenant_admin", "ng_state", False),
    ("tenant_admin", None, False),
])
def test_insurance_viewer_gate(monkeypatch, role, category, allowed) -> None:
    import dependencies
    from dependencies import CurrentUser

    user = CurrentUser(user_id=uuid4(), role=role, org_id=uuid4(), permitted_tenants=["kebbi"])

    async def fake_user(_request):
        return user

    async def fake_type(_org):
        return category

    monkeypatch.setattr(dependencies, "get_current_user", fake_user)
    monkeypatch.setattr(dependencies, "org_tenant_type", fake_type)
    if allowed:
        assert asyncio.run(dependencies.require_insurance_viewer(None)) is user
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(dependencies.require_insurance_viewer(None))
        assert exc.value.status_code == 403


def test_land_basis_is_said_plainly_and_exported() -> None:
    from services.risk_profile import zone_share

    forest = _row("Aowin", 4.8, 100.0, 0.0, "low", [], [])
    forest["figures"]["cropland_pct"] = 0.4
    forest["figures"]["flood"].update(basis="land", rp10_area_pct=1.2, rp100_area_pct=2.0, mapped={})
    text = " ".join(plain_sentences("Aowin", forest["figures"]))
    assert text.startswith("ESA maps little farmland in Aowin (0.4% of the LGA")
    assert "almost none lies in the modelled river flood zones (2.0% in the 1-in-100-year zone)" in text
    assert zone_share(forest["figures"]["flood"]) == "1.2% of land"
    assert zone_share(ROWS[0]["figures"]["flood"]).startswith("33.4% of farmland")
    rows = list(csv.DictReader(io.StringIO(csv_text(ROWS + [forest], 2025, "risk_profile_v1"))))
    by = {r["lga"]: r for r in rows}
    assert by["Aowin"]["flood_basis"] == "land" and by["Aowin"]["land_in_1in10_zone_pct"] == "1.2"
    assert by["Suru"]["flood_basis"] == "farmland"
