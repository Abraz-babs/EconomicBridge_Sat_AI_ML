"""NAIC engagement pack — two PDFs:

  1. NAIC_Introduction_Letter.pdf — formal letter to the MD/CEO proposing a
     briefing + one-season paid pilot (print on letterhead or send as-is).
  2. EconomicBridge_Insurance_Brief.pdf — one-page "Satellite Verification
     for Agricultural Insurance" mapped to the insurer's policy lifecycle.

House rules: no em-dashes in outbound copy; every claim verifiable; the
honest-limits box stays (it is the differentiator, not a weakness).

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_naic_pack.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT_LETTER = Path(r"C:\Users\HP\Downloads\NAIC_Introduction_Letter.pdf")
OUT_BRIEF = Path(r"C:\Users\HP\Downloads\EconomicBridge_Insurance_Brief.pdf")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

DGREEN = colors.HexColor("#0a5c2e")
GREEN = colors.HexColor("#1f8a3b")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
TINT = colors.HexColor("#f0f7f2")
AMBER = colors.HexColor("#b97c10")

BODY, BODY_B = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("EB", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBB", r"C:\Windows\Fonts\arialbd.ttf"))
    BODY, BODY_B = "EB", "EBB"
except Exception:  # noqa: BLE001
    pass

W, H = A4
X0, X1 = 52, W - 52


def wrap(c, text, font, size, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ═════════════════ 1. THE LETTER ═════════════════
c = canvas.Canvas(str(OUT_LETTER), pagesize=A4)
y = H - 50

if LOGO.exists():
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(str(LOGO))
        iw, ih = ir.getSize()
        c.drawImage(ir, X1 - 46, y - 8, width=46, height=46 * ih / iw, mask="auto")
    except Exception:  # noqa: BLE001
        pass
c.setFillColor(DGREEN)
c.setFont(BODY_B, 13)
c.drawString(X0, y, "Bizra Farms Integrated Nigeria Limited")
c.setFillColor(MUTED)
c.setFont(BODY, 8.6)
c.drawString(X0, y - 13, "RC 1929412  ·  operators of EconomicBridge, economicbridge.org")
c.drawString(X0, y - 24, "bizra@economicbridge.org  ·  +234 703 791 9465  ·  Abuja, Nigeria")
y -= 52


def lpara(text, size=9.8, leading=13.6, before=8, font=None):
    global y
    y -= before
    f = font or BODY
    for ln in wrap(c, text, f, size, X1 - X0):
        c.setFont(f, size)
        c.setFillColor(INK)
        c.drawString(X0, y, ln)
        y -= leading


lpara("[Date]", before=0)
lpara("The Managing Director / Chief Executive, ", before=10)
lpara("Nigerian Agricultural Insurance Corporation (NAIC),", before=2)
lpara("Corporate Headquarters, Abuja.", before=2)
lpara("Dear Sir/Madam,", before=14)
lpara("SATELLITE BASED CLAIMS VERIFICATION AND PORTFOLIO MONITORING FOR AGRICULTURAL INSURANCE",
      font=BODY_B, before=10)
lpara("We write to introduce EconomicBridge, a Nigerian satellite intelligence platform operated by "
      "Bizra Farms Integrated Nigeria Limited, and to propose a briefing on how it can reduce the cost "
      "and turnaround time of agricultural claims verification while strengthening underwriting and "
      "portfolio oversight across the Corporation's book.", before=10)
lpara("EconomicBridge is live in production at economicbridge.org. It converts open satellite data from "
      "the European Copernicus programme and NASA into daily, Local Government Area level agricultural "
      "intelligence across 447 LGAs in ten pilot regions, and can activate any additional state within "
      "days. The underlying multi hazard early warning method is patent pending in Nigeria (file "
      "NG/PT/NC/O/2026/23780).", before=8)
lpara("For an agricultural insurer, the platform addresses three operational realities directly:", before=8)
lpara("1. Claims verification. Radar satellites see flood extent through cloud, day or night, within days "
      "of an event and without a field visit. Vegetation indices corroborate drought related losses. "
      "Individual insured farms can be checked singly or as a full claims register (bulk coordinate "
      "processing with export), giving your assessors an evidence base before anyone travels.", before=8)
lpara("2. Underwriting. Our archive of satellite observations from 2023 to date, covering more than "
      "31,000 monthly readings across 447 LGAs, supports pre season risk zoning: flood prone and "
      "drought frequency profiles at LGA resolution for premium and exposure decisions.", before=8)
lpara("3. Portfolio oversight. Autonomous daily satellite scans raise flood, drought and land "
      "disturbance alerts through the season, delivered by dashboard and scheduled email digests to "
      "your operations desk.", before=8)
lpara("We would welcome the opportunity to demonstrate the platform to your technical team, including a "
      "retrospective analysis over a state and season of your choosing from 2023 to 2026, so the "
      "Corporation can judge the signals against events it already knows. Should the demonstration merit "
      "it, we propose a one season paid pilot in one or two states, with service levels and data "
      "protection terms (NDPA 2023) provided in writing.", before=8)
lpara("Thank you for your consideration. We are at your convenience for a meeting in Abuja.", before=8)
lpara("Yours faithfully,", before=14)
lpara("Abdullahi Zuru Ibrahim", font=BODY_B, before=26)
lpara("Founder / Chief Executive Officer", before=2)
lpara("EconomicBridge  ·  Bizra Farms Integrated Nigeria Limited", before=2)
lpara("Encl.: Satellite Verification for Agricultural Insurance (one page brief); System Architecture.", before=10)

c.showPage()
c.save()
print("built", OUT_LETTER)

# ═════════════════ 2. THE BRIEF ═════════════════
c = canvas.Canvas(str(OUT_BRIEF), pagesize=A4)
X0, X1 = 42, W - 42
y = H - 48

if LOGO.exists():
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(str(LOGO))
        iw, ih = ir.getSize()
        c.drawImage(ir, X0, y - 8, width=38, height=38 * ih / iw, mask="auto")
    except Exception:  # noqa: BLE001
        pass
c.setFillColor(DGREEN)
c.setFont(BODY_B, 15)
c.drawString(X0 + 46, y + 8, "Satellite Verification for Agricultural Insurance")
c.setFillColor(MUTED)
c.setFont(BODY, 8.8)
c.drawString(X0 + 46, y - 6, "EconomicBridge · live at economicbridge.org · patent pending NG/PT/NC/O/2026/23780 · Bizra Farms Ltd")
y -= 36


def section(label, accent=GREEN):
    global y
    c.setFillColor(TINT)
    c.setStrokeColor(accent)
    c.setLineWidth(0.8)
    c.roundRect(X0, y - 16, X1 - X0, 19, 4, stroke=1, fill=1)
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 9.6)
    c.drawString(X0 + 7, y - 10.5, label)
    y -= 28


def bpara(text, size=8.6, leading=11.2, bold_head=None, indent=0):
    global y
    maxw = X1 - X0 - indent
    full = (bold_head + " " + text) if bold_head else text
    lines = wrap(c, full, BODY, size, maxw)
    for i, ln in enumerate(lines):
        if i == 0 and bold_head:
            c.setFont(BODY_B, size)
            c.setFillColor(INK)
            c.drawString(X0 + indent, y, bold_head)
            off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
            c.setFont(BODY, size)
            c.drawString(X0 + indent + off, y, ln[len(bold_head):].lstrip())
        else:
            c.setFont(BODY, size)
            c.setFillColor(INK)
            c.drawString(X0 + indent, y, ln)
        y -= leading
    y -= 2.5


section("THE OPERATIONAL PROBLEM")
bpara("Agricultural loss assessment in Nigeria is slow and expensive: adjusters travel to remote, often "
      "flooded farms; claims age while evidence degrades; and underwriting is done with little "
      "location specific risk data. Every week of claims delay costs trust and money on both sides "
      "of the policy.")

section("WHAT THE PLATFORM DOES ACROSS THE POLICY LIFECYCLE")
bpara("LGA level risk zoning before the season: flood prone flags and drought frequency profiles "
      "computed from our 2023 to 2026 satellite archive (31,000+ monthly radar and vegetation readings "
      "across 447 LGAs). Any additional state can be activated within days.",
      bold_head="1. Underwriting.")
bpara("autonomous daily satellite scans through the season raise flood, drought and land disturbance "
      "alerts per LGA, delivered in a dedicated dashboard workspace and scheduled email digests to "
      "your operations desk. Radar works through cloud, day and night, all wet season.",
      bold_head="2. In-season monitoring.")
bpara("radar flood extent within days of an event, before any field visit; vegetation decline "
      "corroboration for drought claims; and per farm verification of individual insured plots, "
      "singly or as a bulk claims register (paste or upload coordinates, results exported to CSV), "
      "each with the analysed area, satellite pass history and reading provenance shown.",
      bold_head="3. Claims verification.")
bpara("planting and emergence checks against declared coverage; wrong coordinate detection on "
      "submitted farm locations; season long vegetation history per plot against its own baseline.",
      bold_head="4. Fraud control.")
bpara("isolated tenant workspace, role based access, audit logged queries, NDPA 2023 data protection "
      "addendum, 99.5% availability service level with externally measured uptime, and disaster "
      "recovery rehearsed and documented.",
      bold_head="5. Enterprise delivery.")

section("WHAT WE DO NOT CLAIM", accent=AMBER)
bpara("We state limits plainly because verification businesses live on credibility. We do not forecast "
      "yields without locally calibrated data. Reference imagery shown for context is labelled as such "
      "and is never presented as detection evidence; detection comes from Copernicus and NASA sensors "
      "with per pass provenance. Model outputs carry published confidence and route to human review. "
      "Every claim in this brief can be checked live at economicbridge.org.")

section("PROPOSED ENGAGEMENT")
bpara("technical briefing and live demonstration in Abuja, including a retrospective analysis over a "
      "state and season of NAIC's choosing (2023 to 2026), judged against events the Corporation "
      "already knows.", bold_head="Step 1:")
bpara("one season paid pilot in one or two states: risk zoning report before the season, daily "
      "monitoring and alert digests through it, and claims verification support on request. Service "
      "level agreement and NDPA data protection addendum provided at signature. Commercial terms on "
      "request.", bold_head="Step 2:")

c.setFillColor(MUTED)
c.setFont(BODY, 7.6)
c.drawCentredString((X0 + X1) / 2, 40,
                    "EconomicBridge · Bizra Farms Integrated Nigeria Limited (RC 1929412) · bizra@economicbridge.org · "
                    "+234 703 791 9465 · economicbridge.org · July 2026")

c.showPage()
c.save()
print("built", OUT_BRIEF)
