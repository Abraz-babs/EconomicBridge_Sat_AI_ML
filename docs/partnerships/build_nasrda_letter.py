"""Generate the NASRDA partnership letter as a branded PDF.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nasrda_letter.py
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
OUT = Path(__file__).parent / "Bizra_NASRDA_Partnership_Letter.pdf"

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
    Paragraph("The Director-General & Chief Executive Officer", ref),
    Paragraph("National Space Research and Development Agency (NASRDA)", ref),
    Paragraph("Obasanjo Space Centre, Airport Road, Lugbe", ref),
    Paragraph("Abuja, Nigeria", ref),
    Spacer(1, 8),

    Paragraph(
        "PROPOSAL FOR PARTNERSHIP: APPLYING EARTH OBSERVATION FOR AGRICULTURE, "
        "FOOD SECURITY AND DISASTER RESILIENCE, THROUGH A NIGERIAN-BUILT "
        "SATELLITE INTELLIGENCE PLATFORM", subj),

    Paragraph("Dear Sir,", body),

    Paragraph(
        "On behalf of <b>Bizra Farms Integrated Nigeria Limited</b>, I write "
        "with great enthusiasm to propose a partnership with the National Space "
        "Research and Development Agency. We are a Nigerian company that has "
        "built and deployed <b>EconomicBridge</b>, a satellite and artificial "
        "intelligence platform that turns Earth observation into real, "
        "on-the-ground impact for agriculture, food security and disaster "
        "response. In doing so, we believe we are helping to realise NASRDA's "
        "founding mandate: the application of space science and technology for "
        "the socio-economic benefit of our nation.", body),

    Paragraph(
        "EconomicBridge is live today on secure cloud infrastructure, already "
        "covering more than 700 local government areas across Nigeria, Ghana "
        "and Senegal. It diagnoses crop disease using AI, detects floods and "
        "drought from satellite radar, predicts farmland conflict 24 to 72 "
        "hours ahead, and maps poverty and population from space, then delivers "
        "warnings to communities by SMS in their own languages. It currently "
        "draws on Copernicus, NASA, World Bank and UNICEF data, and is designed "
        "to scale to all 36 states and the FCT.", body),

    Paragraph(
        "<b>Why we are writing to NASRDA.</b> A platform like this is exactly "
        "where Nigerian space capability should lead. We would be honoured to "
        "integrate NASRDA's own Earth-observation assets, including NigeriaSat "
        "imagery and the work of the National Centre for Remote Sensing, so "
        "that Nigerian satellite data visibly drives applications that protect "
        "Nigerian farmers and communities. Together we can demonstrate a "
        "homegrown success story: Nigerian data, Nigerian innovation, and "
        "measurable Nigerian impact.", body),

    Paragraph("<b>Proposed areas of collaboration:</b>", body),
    Paragraph(
        "• <b>Data integration:</b> incorporate NASRDA and NigeriaSat "
        "Earth-observation data into the platform's crop, flood and land-use "
        "intelligence, alongside our existing international sources.<br/>"
        "• <b>Joint demonstration:</b> a flagship showcase of applied Earth "
        "observation for food security and disaster early warning across pilot "
        "states.<br/>"
        "• <b>Applications and capacity:</b> a live reference platform for "
        "NASRDA's remote-sensing application centres and partner agencies.<br/>"
        "• <b>Last-mile impact:</b> taking space-derived insight all the way to "
        "the farmer, through multilingual SMS and partner networks.", body),

    Paragraph(
        "This partnership would turn NASRDA's mandate into something the nation "
        "can see and feel: a deployed, working example of space technology "
        "improving lives and livelihoods. We would be honoured to give you and "
        "your technical teams a live demonstration at your convenience, and to "
        "explore a data-sharing arrangement and a memorandum of understanding.",
        body),

    Spacer(1, 6),
    Paragraph(
        "Please accept, Sir, the assurances of our highest regard.", body),
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
    title="Bizra Farms - NASRDA Partnership Proposal",
    author="Bizra Farms Integrated Nigeria Limited",
)
doc.build(story)
shutil.copy(OUT, Path(r"C:\Users\HP\Downloads") / OUT.name)
print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes); copied to Downloads")
