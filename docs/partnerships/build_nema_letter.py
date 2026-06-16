"""Generate the NEMA partnership letter as a branded PDF (Bizra letterhead).

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nema_letter.py
"""
from __future__ import annotations

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

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _sig import signature_image  # noqa: E402

LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")
OUT = Path(__file__).parent / "Bizra_NEMA_Partnership_Letter.pdf"
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

# Logo scaled to a letterhead width, aspect preserved (~1024x390).
logo_w = 360
logo_h = logo_w * 390 / 1024

story = [
    Image(str(LOGO), width=logo_w, height=logo_h, hAlign="CENTER"),
    Spacer(1, 4),
    HRFlowable(width="100%", thickness=1.6, color=GREEN, spaceBefore=2, spaceAfter=2),
    HRFlowable(width="100%", thickness=0.6, color=BROWN, spaceAfter=10),

    Paragraph(date.today().strftime("%d %B %Y"), ref),
    Spacer(1, 6),
    Paragraph("The Director-General", ref),
    Paragraph("National Emergency Management Agency (NEMA)", ref),
    Paragraph("National Headquarters, No. 8 Adetokunbo Ademola Crescent", ref),
    Paragraph("Maitama, Abuja, Nigeria", ref),
    Spacer(1, 8),

    Paragraph(
        "PROPOSAL FOR PARTNERSHIP: DEPLOYMENT OF THE ECONOMICBRIDGE "
        "SATELLITE INTELLIGENCE PLATFORM FOR DISASTER EARLY WARNING, "
        "RESPONSE TARGETING, AND RESILIENCE PLANNING", subj),

    Paragraph("Dear Madam,", body),

    Paragraph(
        "On behalf of <b>Bizra Farms Integrated Nigeria Limited</b>, I write to "
        "propose a strategic partnership with the National Emergency Management "
        "Agency. We build and operate satellite and AI intelligence systems "
        "that turn live earth observation data into early warnings and "
        "decision support for government, and we would like to place that "
        "capability at the service of NEMA's disaster management mandate.", body),

    Paragraph(
        "<b>EconomicBridge</b> is a multi tenant satellite intelligence "
        "platform, live on secure cloud infrastructure, that gives decision "
        "makers a real time, local government level picture of conditions "
        "across the country. It draws on live data from the European Copernicus "
        "(Sentinel-1 and Sentinel-2) satellites, NASA, the World Bank and "
        "UNICEF, currently covering over 700 local government areas across "
        "Nigeria and neighbouring ECOWAS states. It is designed to scale to "
        "all 36 states and the FCT.", body),

    Paragraph(
        "<b>The proposed project.</b> We will activate a dedicated, secure "
        "national account for NEMA, configured for the Agency's mandate, and "
        "work with your nominated officers over an initial pilot period to "
        "embed the platform into your early warning and response workflows. "
        "This is offered at no cost during the pilot, with NEMA's data visible "
        "only to your team. Beyond the pilot, we anticipate transitioning to a "
        "subscription arrangement by mutual agreement.", body),

    Paragraph(
        "<b>What the platform delivers for NEMA:</b>", body),
    Paragraph(
        "• <b>Flood &amp; drought early warning (ShockGuard):</b> detection from "
        "Sentinel-1 radar that sees through cloud cover, day or night, for "
        "advance warning ahead of disasters.<br/>"
        "• <b>Active fire monitoring:</b> daily NASA FIRMS detections of bush "
        "and wildfire across the country.<br/>"
        "• <b>Conflict &amp; displacement early warning:</b> 24 to 72 hour "
        "prediction of farmer/herder and encroachment flashpoints that drive "
        "population displacement.<br/>"
        "• <b>Population &amp; vulnerability mapping:</b> settlement level "
        "population and poverty intensity from nightlight and population "
        "satellite data, to target relief where need is greatest.<br/>"
        "• <b>Relief coordination:</b> a shared view of agency coverage to "
        "reduce duplication and close gaps.<br/>"
        "• <b>National oversight:</b> a single nationwide dashboard matching "
        "NEMA's federal mandate, with automated monthly situation reports.", body),

    Paragraph(
        "<b>And beyond response.</b> Because the platform also monitors "
        "agriculture, food security, livelihoods and education access, it "
        "supports NEMA's wider role in disaster <i>risk reduction</i> and "
        "post disaster recovery. Our registration free, multilingual SMS "
        "alerting can also reach affected communities directly through partner "
        "agencies, including citizens without smartphones.", body),

    Paragraph(
        "We would be honoured to give your team a live demonstration at your "
        "convenience and to discuss how EconomicBridge can strengthen the "
        "Agency's operations. Kindly nominate one or two officers as points of "
        "contact, and we will activate NEMA's account and provide guided "
        "onboarding immediately.", body),

    Spacer(1, 6),
    Paragraph("Please accept the assurances of our highest regard.", body),
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
    title="Bizra Farms — NEMA Partnership Proposal",
    author="Bizra Farms Integrated Nigeria Limited",
)
doc.build(story)
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
