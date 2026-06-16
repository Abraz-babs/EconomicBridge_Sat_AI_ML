"""Generate the Nasarawa State beta-access letter as a branded PDF.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nasarawa_letter.py
"""
from __future__ import annotations

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

LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")
OUT = Path(__file__).parent / "Bizra_Nasarawa_Beta_Access_Letter.pdf"
_SIGNATURE = signature_image(target_width=150)

GREEN = colors.HexColor("#1f8a3b")
BROWN = colors.HexColor("#6e2b2b")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10.5, leading=15,
                      textColor=INK, alignment=TA_JUSTIFY, spaceAfter=8)
small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.3, leading=11,
                       textColor=GREY)
ref = ParagraphStyle("ref", parent=body, alignment=0, spaceAfter=2)
subj = ParagraphStyle("subj", parent=body, fontName="Helvetica-Bold",
                      textColor=BROWN, alignment=0, spaceBefore=6, spaceAfter=8)
sign = ParagraphStyle("sign", parent=body, alignment=0, spaceAfter=1)

logo_w = 360
logo_h = logo_w * 390 / 1024

story = [
    Image(str(LOGO), width=logo_w, height=logo_h, hAlign="CENTER"),
    Spacer(1, 4),
    HRFlowable(width="100%", thickness=1.6, color=GREEN, spaceBefore=2, spaceAfter=2),
    HRFlowable(width="100%", thickness=0.6, color=BROWN, spaceAfter=10),

    Paragraph(date.today().strftime("%d %B %Y"), ref),
    Spacer(1, 6),
    Paragraph("His Excellency, The Executive Governor", ref),
    Paragraph("Nasarawa State Government", ref),
    Paragraph("Government House, Lafia", ref),
    Paragraph("Nasarawa State, Nigeria", ref),
    Spacer(1, 8),

    Paragraph(
        "OFFER OF COMPLIMENTARY BETA ACCESS TO THE ECONOMICBRIDGE SATELLITE "
        "INTELLIGENCE PLATFORM FOR NASARAWA STATE", subj),

    Paragraph("Your Excellency,", body),

    Paragraph(
        "On behalf of <b>Bizra Farms Integrated Nigeria Limited</b>, I write to "
        "offer the Nasarawa State Government complimentary beta access to "
        "<b>EconomicBridge</b>, a satellite and artificial intelligence platform "
        "that gives a state government a live, local government level picture of "
        "what is happening on the ground across its territory.", body),

    Paragraph(
        "EconomicBridge is live on secure cloud infrastructure and draws on "
        "real data from the European Copernicus (Sentinel-1 and Sentinel-2) "
        "satellites, NASA, the World Bank and UNICEF. We are pleased to extend "
        "this offer to Nasarawa State at no cost, covering all 13 Local "
        "Government Areas, so that Your Excellency's administration can see its "
        "value firsthand.", body),

    Paragraph("<b>What the platform offers Nasarawa State:</b>", body),
    Paragraph(
        "• <b>Agriculture:</b> AI diagnosis of crop disease from a single leaf "
        "photo, satellite monitoring of crop health, and 24 to 72 hour early "
        "warning of farmland conflict and encroachment.<br/>"
        "• <b>Disaster preparedness:</b> flood and drought detection from "
        "satellite radar that sees through cloud cover, for early warning.<br/>"
        "• <b>Poverty and population mapping:</b> settlement level population "
        "and poverty intensity from night light satellite data, so the State "
        "can direct budget and intervention where the need is greatest.<br/>"
        "• <b>Education:</b> school access and connectivity mapping to target "
        "educational investment.<br/>"
        "• <b>Economy:</b> income and cost of living tracking across the "
        "State.<br/>"
        "• <b>Aid coordination:</b> a shared view of which agencies operate "
        "where, to reduce duplication and close gaps in coverage.", body),

    Paragraph(
        "Nasarawa State's data would be visible only to your nominated team, "
        "fully isolated and secure, and aligned with the Nigeria Data "
        "Protection Act. The platform also delivers automated monthly reports, "
        "and can reach communities directly through multilingual SMS alerts in "
        "partnership with relevant agencies, including citizens without "
        "smartphones.", body),

    Paragraph(
        "We would be honoured to give Your Excellency or your nominated team a "
        "live demonstration at your convenience. Kindly nominate one or two "
        "officers as points of contact, and we will activate the State's "
        "account and provide guided onboarding immediately.", body),

    Spacer(1, 6),
    Paragraph(
        "Please accept, Your Excellency, the assurances of our highest regard.",
        body),
    Spacer(1, 10),
    Paragraph("Yours faithfully,", sign),
    Spacer(1, 8),
    _SIGNATURE or Paragraph("_______________________________", sign),
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

doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=14 * mm, bottomMargin=14 * mm,
    title="Bizra Farms - Nasarawa State Beta Access Offer",
    author="Bizra Farms Integrated Nigeria Limited",
)
doc.build(story)
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
