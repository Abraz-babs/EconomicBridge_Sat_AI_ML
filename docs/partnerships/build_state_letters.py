"""Generate beta-access letters for the remaining pilot states from one config.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_state_letters.py

One branded PDF per state in STATES, written to docs/partnerships/ and copied
to Downloads. Shares the Bizra letterhead + signature helper with the NEMA /
Nasarawa letters.
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer,
)

sys.path.insert(0, str(Path(__file__).parent))
from _sig import signature_image  # noqa: E402

HERE = Path(__file__).parent
DOWNLOADS = Path(r"C:\Users\HP\Downloads")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

GREEN = colors.HexColor("#1f8a3b")
BROWN = colors.HexColor("#6e2b2b")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")

# Per-pilot config. LGA counts match the platform's geoBoundaries admin-2 set.
STATES = [
    dict(key="kebbi", region="Kebbi State", subj="KEBBI STATE",
         govt="Kebbi State Government", house="Government House, Birnin Kebbi",
         state_line="Kebbi State, Nigeria", lgas=21, term="Local Government Areas",
         short="State"),
    dict(key="benue", region="Benue State", subj="BENUE STATE",
         govt="Benue State Government", house="Government House, Makurdi",
         state_line="Benue State, Nigeria", lgas=23, term="Local Government Areas",
         short="State"),
    dict(key="plateau", region="Plateau State", subj="PLATEAU STATE",
         govt="Plateau State Government", house="Government House, Jos",
         state_line="Plateau State, Nigeria", lgas=17, term="Local Government Areas",
         short="State"),
    dict(key="kaduna", region="Kaduna State", subj="KADUNA STATE",
         govt="Kaduna State Government", house="Sir Kashim Ibrahim House (Government House)",
         state_line="Kaduna, Kaduna State, Nigeria", lgas=23, term="Local Government Areas",
         short="State"),
    dict(key="niger", region="Niger State", subj="NIGER STATE",
         govt="Niger State Government", house="Government House, Minna",
         state_line="Niger State, Nigeria", lgas=25, term="Local Government Areas",
         short="State"),
    dict(key="zamfara", region="Zamfara State", subj="ZAMFARA STATE",
         govt="Zamfara State Government", house="Government House, Gusau",
         state_line="Zamfara State, Nigeria", lgas=14, term="Local Government Areas",
         short="State"),
    # FCT is administered by the Honourable Minister, not a Governor.
    dict(key="fct", region="the Federal Capital Territory",
         subj="THE FEDERAL CAPITAL TERRITORY",
         govt="the Federal Capital Territory Administration",
         house="Federal Capital Territory Administration, Area 11, Garki",
         state_line="Abuja, Nigeria", lgas=6, term="Area Councils",
         short="Territory", minister=True),
]


def styles():
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10.5, leading=15,
                          textColor=INK, alignment=TA_JUSTIFY, spaceAfter=8)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.3, leading=11,
                           textColor=GREY)
    ref = ParagraphStyle("ref", parent=body, alignment=0, spaceAfter=2)
    subj = ParagraphStyle("subj", parent=body, fontName="Helvetica-Bold",
                          textColor=BROWN, alignment=0, spaceBefore=6, spaceAfter=8)
    sign = ParagraphStyle("sign", parent=body, alignment=0, spaceAfter=1)
    return body, small, ref, subj, sign


def build(cfg: dict) -> Path:
    body, small, ref, subj, sign = styles()
    minister = cfg.get("minister", False)
    salutation = "Honourable Minister," if minister else "Your Excellency,"
    principal_admin = "your administration" if minister else "Your Excellency's administration"
    principal_demo = "you or your nominated team" if minister else "Your Excellency or your nominated team"
    close = (
        "Please accept, Honourable Minister, the assurances of our highest regard."
        if minister else
        "Please accept, Your Excellency, the assurances of our highest regard."
    )
    recipient = (
        ["The Honourable Minister"] if minister
        else ["His Excellency, The Executive Governor"]
    ) + [cfg["govt"], cfg["house"], cfg["state_line"]]

    logo_w = 360
    logo_h = logo_w * 390 / 1024

    story = [
        Image(str(LOGO), width=logo_w, height=logo_h, hAlign="CENTER"),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=1.6, color=GREEN, spaceBefore=2, spaceAfter=2),
        HRFlowable(width="100%", thickness=0.6, color=BROWN, spaceAfter=10),
        Paragraph(date.today().strftime("%d %B %Y"), ref),
        Spacer(1, 6),
        *[Paragraph(line, ref) for line in recipient],
        Spacer(1, 8),
        Paragraph(
            "OFFER OF COMPLIMENTARY BETA ACCESS TO THE ECONOMICBRIDGE SATELLITE "
            f"INTELLIGENCE PLATFORM FOR {cfg['subj']}", subj),
        Paragraph(salutation, body),
        Paragraph(
            "On behalf of <b>Bizra Farms Integrated Nigeria Limited</b>, I write to "
            f"offer the {cfg['govt']} complimentary beta access to "
            "<b>EconomicBridge</b>, a satellite and artificial intelligence platform "
            f"that gives {cfg['region']}'s administration a live, local government "
            "level picture of what is happening on the ground across its territory.",
            body),
        Paragraph(
            "EconomicBridge is live on secure cloud infrastructure and draws on real "
            "data from the European Copernicus (Sentinel-1 and Sentinel-2) "
            "satellites, NASA, the World Bank and UNICEF. We are pleased to offer "
            f"this access to {cfg['region']} free of charge for an initial pilot "
            f"period, covering all {cfg['lgas']} {cfg['term']}, so that "
            f"{principal_admin} can evaluate its value firsthand. Beyond the pilot, "
            "we anticipate transitioning to a modest subscription arrangement by "
            "mutual agreement.", body),
        Paragraph(f"<b>What the platform offers {cfg['region']}:</b>", body),
        Paragraph(
            "• <b>Agriculture:</b> AI diagnosis of crop disease from a single leaf "
            "photo, satellite monitoring of crop health, and 24 to 72 hour early "
            "warning of farmland conflict and encroachment.<br/>"
            "• <b>Disaster preparedness:</b> flood and drought detection from "
            "satellite radar that sees through cloud cover, for early warning.<br/>"
            "• <b>Poverty and population mapping:</b> settlement level population "
            "and poverty intensity from night light satellite data, so the "
            f"{cfg['short']} can direct budget and intervention where the need is "
            "greatest.<br/>"
            "• <b>Education:</b> school access and connectivity mapping to target "
            "educational investment.<br/>"
            f"• <b>Economy:</b> income and cost of living tracking across the "
            f"{cfg['short']}.<br/>"
            "• <b>Aid coordination:</b> a shared view of which agencies operate "
            "where, to reduce duplication and close gaps in coverage.", body),
        Paragraph(
            f"{cfg['region']}'s data would be visible only to your nominated team, "
            "fully isolated and secure, and aligned with the Nigeria Data "
            "Protection Act. The platform also delivers automated monthly reports, "
            "and can reach communities directly through multilingual SMS alerts in "
            "partnership with relevant agencies, including citizens without "
            "smartphones.", body),
        Paragraph(
            f"We would be honoured to give {principal_demo} a live demonstration at "
            "your convenience. Kindly nominate one or two officers as points of "
            f"contact, and we will activate the {cfg['short']}'s account and provide "
            "guided onboarding immediately.", body),
        Spacer(1, 6),
        Paragraph(close, body),
        Spacer(1, 10),
        Paragraph("Yours faithfully,", sign),
        Spacer(1, 8),
        signature_image(target_width=150) or Paragraph("_______________________________", sign),
        Spacer(1, 2),
        Paragraph("<b>Abdullahi Zuru Ibrahim</b>", sign),
        Paragraph("Founder &amp; CEO", sign),
        Paragraph("Bizra Farms Integrated Nigeria Limited", sign),
        Spacer(1, 14),
        HRFlowable(width="100%", thickness=0.6, color=BROWN, spaceAfter=4),
        Paragraph(
            "Bizra Farms Integrated Nigeria Limited &nbsp;|&nbsp; "
            "No. 32A ITM, Sabara Road, Gesse Phase 1, Birnin Kebbi, Kebbi State "
            "&nbsp;|&nbsp; bizrafarms@gmail.com &nbsp;|&nbsp; +234 703 791 9465",
            small),
    ]

    out = HERE / f"Bizra_{cfg['key'].title()}_Beta_Access_Letter.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Bizra Farms - {cfg['region']} Beta Access Offer",
        author="Bizra Farms Integrated Nigeria Limited",
    )
    doc.build(story)
    shutil.copy(out, DOWNLOADS / out.name)
    return out


if __name__ == "__main__":
    for cfg in STATES:
        p = build(cfg)
        print(f"  {cfg['region']:32} -> {p.name}")
    print("done; copies in Downloads")
