"""Generate the ECOWAS Commission partnership letter as a branded PDF.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_ecowas_letter.py
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

LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")
OUT = Path(__file__).parent / "Bizra_ECOWAS_Partnership_Letter.pdf"

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
    Paragraph("His Excellency, The President", ref),
    Paragraph("ECOWAS Commission", ref),
    Paragraph("101 Yakubu Gowon Crescent, Asokoro District", ref),
    Paragraph("P.M.B 401, Abuja, Nigeria", ref),
    Spacer(1, 8),

    Paragraph(
        "PROPOSAL FOR PARTNERSHIP: REGIONAL DEPLOYMENT OF THE ECONOMICBRIDGE "
        "SATELLITE INTELLIGENCE PLATFORM FOR FOOD SECURITY, DISASTER EARLY "
        "WARNING AND REGIONAL RESILIENCE", subj),

    Paragraph("Your Excellency,", body),

    Paragraph(
        "On behalf of <b>Bizra Farms Integrated Nigeria Limited</b>, I write to "
        "propose a partnership with the ECOWAS Commission. We build and operate "
        "satellite and artificial intelligence systems that turn live earth "
        "observation data into early warnings and decision support, and we "
        "believe this capability can serve the Community's goals in food "
        "security, disaster preparedness and regional integration.", body),

    Paragraph(
        "<b>EconomicBridge</b> is a multi tenant satellite intelligence platform, "
        "live on secure cloud infrastructure, that provides a real time, local "
        "government level picture of conditions on the ground. It is already "
        "operational across Nigeria, Ghana and Senegal, covering more than 700 "
        "administrative areas, and is designed to scale to all fifteen ECOWAS "
        "member states. It draws on live data from the European Copernicus "
        "(Sentinel-1 and Sentinel-2) satellites, NASA, the World Bank and "
        "UNICEF.", body),

    Paragraph(
        "<b>The proposed partnership.</b> We will provide the Commission a "
        "dedicated regional dashboard with a consolidated view across member "
        "states, configured for the relevant departments, beginning with a "
        "complimentary pilot over the states already live and extending to "
        "others by agreement. Each member state's data remains isolated and "
        "secure, while the Commission gains the region wide picture its mandate "
        "requires.", body),

    Paragraph("<b>What the platform offers the Community:</b>", body),
    Paragraph(
        "• <b>Regional food security and agriculture:</b> satellite monitoring "
        "of crop health, AI crop disease diagnosis and market price "
        "intelligence, in support of the ECOWAS Agricultural Policy.<br/>"
        "• <b>Disaster early warning:</b> flood and drought detection from "
        "satellite radar that sees through cloud cover, across borders.<br/>"
        "• <b>Conflict and displacement early warning:</b> 24 to 72 hour "
        "prediction of flashpoints that drive cross border displacement, "
        "complementing the Community's early warning network.<br/>"
        "• <b>Poverty and population mapping:</b> settlement level population "
        "and vulnerability from satellite data, to target regional "
        "programmes.<br/>"
        "• <b>Humanitarian coordination:</b> a shared view of agency coverage "
        "across member states, to reduce duplication and close gaps.<br/>"
        "• <b>Regional oversight:</b> a single dashboard with per member state "
        "breakdowns and automated periodic reports.", body),

    Paragraph(
        "The platform also delivers alerts directly to communities through "
        "multilingual SMS, in English, French and Portuguese, reaching citizens "
        "without smartphones through partner agencies. This aligns naturally "
        "with the Community's linguistic and humanitarian reach.", body),

    Paragraph(
        "We would be honoured to give Your Excellency or the relevant "
        "departments a live demonstration at your convenience. Kindly nominate "
        "a focal point, and we will provide guided onboarding and a regional "
        "pilot immediately.", body),

    Spacer(1, 6),
    Paragraph(
        "Please accept, Your Excellency, the assurances of our highest regard.",
        body),
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

doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=14 * mm, bottomMargin=14 * mm,
    title="Bizra Farms - ECOWAS Commission Partnership Proposal",
    author="Bizra Farms Integrated Nigeria Limited",
)
doc.build(story)
shutil.copy(OUT, Path(r"C:\Users\HP\Downloads") / OUT.name)
print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes); copied to Downloads")
