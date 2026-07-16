"""Founder profile one-pager — Abdullahi Zuru Ibrahim.

Simple, verifiable, honest: every claim on this page can be checked
(live URL, filing number, commit history). Citadel uses the approved
"built and pitched" phrasing; prize applications are marked in review.

    apps/api/.venv/Scripts/python.exe docs/company/build_founder_profile.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\HP\Downloads\Abdullahi_Zuru_Ibrahim_Profile.pdf")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

DGREEN = colors.HexColor("#0a5c2e")
GREEN = colors.HexColor("#1f8a3b")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
TINT = colors.HexColor("#f0f7f2")

BODY, BODY_B = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("EB", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBB", r"C:\Windows\Fonts\arialbd.ttf"))
    BODY, BODY_B = "EB", "EBB"
except Exception:  # noqa: BLE001
    pass

W, H = A4
c = canvas.Canvas(str(OUT), pagesize=A4)
X0, X1 = 46, W - 46


def wrap(text, font, size, maxw):
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


def para(y, text, size=9.2, leading=12.6, bold_head=None, indent=0, color=INK):
    maxw = X1 - X0 - indent
    full = (bold_head + " " + text) if bold_head else text
    lines = wrap(full, BODY, size, maxw)
    for i, ln in enumerate(lines):
        if i == 0 and bold_head:
            c.setFont(BODY_B, size)
            c.setFillColor(color)
            c.drawString(X0 + indent, y, bold_head)
            off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
            c.setFont(BODY, size)
            c.setFillColor(INK)
            c.drawString(X0 + indent + off, y, ln[len(bold_head):].lstrip())
        else:
            c.setFont(BODY, size)
            c.setFillColor(INK)
            c.drawString(X0 + indent, y, ln)
        y -= leading
    return y - 3


def section(y, label):
    c.setFillColor(TINT)
    c.setStrokeColor(GREEN)
    c.setLineWidth(0.8)
    c.roundRect(X0, y - 16, X1 - X0, 19, 4, stroke=1, fill=1)
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 9.8)
    c.drawString(X0 + 7, y - 10.5, label)
    return y - 30


def bullet(y, text, bold_head=None, size=9.0, leading=12.2):
    c.setFillColor(GREEN)
    c.setFont(BODY_B, size)
    c.drawString(X0 + 2, y, "—")
    maxw = X1 - X0 - 18
    full = (bold_head + " " + text) if bold_head else text
    lines = wrap(full, BODY, size, maxw)
    for i, ln in enumerate(lines):
        if i == 0 and bold_head:
            c.setFont(BODY_B, size)
            c.setFillColor(INK)
            c.drawString(X0 + 16, y, bold_head)
            off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
            c.setFont(BODY, size)
            c.drawString(X0 + 16 + off, y, ln[len(bold_head):].lstrip())
        else:
            c.setFont(BODY, size)
            c.setFillColor(INK)
            c.drawString(X0 + 16, y, ln)
        y -= leading
    return y - 3


# ── Header ─────────────────────────────────────────────────────────────────
y = H - 52
if LOGO.exists():
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(str(LOGO))
        iw, ih = ir.getSize()
        c.drawImage(ir, X1 - 44, y - 10, width=44, height=44 * ih / iw, mask="auto")
    except Exception:  # noqa: BLE001
        pass
c.setFillColor(DGREEN)
c.setFont(BODY_B, 21)
c.drawString(X0, y, "Abdullahi Zuru Ibrahim")
c.setFillColor(INK)
c.setFont(BODY_B, 10.5)
c.drawString(X0, y - 17, "Founder & CEO, EconomicBridge  ·  Bizra Farms Integrated Nigeria Limited")
c.setFillColor(MUTED)
c.setFont(BODY, 9)
c.drawString(X0, y - 31, "Abuja, Nigeria (from Kebbi State)  ·  bizra@economicbridge.org  ·  +234 703 791 9465  ·  economicbridge.org")
y -= 52

# ── Positioning ────────────────────────────────────────────────────────────
y = para(y, "I build satellite intelligence systems for African governments — and I build them honestly. "
            "My platform, EconomicBridge, turns free, open satellite data (Copernicus, NASA) into daily "
            "decision intelligence for food security, farmland protection and disaster early warning, "
            "running live and unattended over 447 Local Government Areas across Nigeria, Ghana and Senegal. "
            "Everything I claim can be clicked, checked or verified: the platform is public, the patent is "
            "filed, and every alert on screen carries its satellite provenance.", size=9.6, leading=13.2)

# ── What I've built ────────────────────────────────────────────────────────
y = section(y, "WHAT I'VE BUILT — ECONOMICBRIDGE  (live at economicbridge.org)")
y = bullet(y, "seven decision modules (farmland-encroachment early warning, crop health, flood/drought, "
              "poverty mapping, aid coordination, economic mobility, skills access) on one multi-tenant "
              "platform — each state or institution in its own isolated workspace.",
           bold_head="A national-scale platform:")
y = bullet(y, "a daily satellite chain (Sentinel-1 radar, Sentinel-2 optical, NASA FIRMS fire, VIIRS "
              "night-lights) fuses independent signals per LGA and raises human-verified early warnings — "
              "unattended, every morning, with an auditable run log.",
           bold_head="Autonomous EO pipeline:")
y = bullet(y, "field officers verify any farm coordinate in seconds (single or bulk), with cloud-masked "
              "NDVI, radar history, stress early-warning and a trained ResNet-50 leaf-disease classifier "
              "as the ground-level confirmation layer.",
           bold_head="Field tools:")
y = bullet(y, "AWS (ECS, RDS, Terraform-provisioned), externally monitored uptime with a 99.5% SLA, "
              "rehearsed disaster-recovery, NDPA-2023 data-protection paperwork, and sub-day customer "
              "onboarding. Free multilingual SMS advisories reach farmers through their institutions — "
              "farmers never need a smartphone or registration.",
           bold_head="Production-grade operations:")

# ── Highlights ─────────────────────────────────────────────────────────────
y = section(y, "SELECTED HIGHLIGHTS — 2026")
y = bullet(y, "Nigerian patent application filed for the satellite-based multi-hazard early-warning system "
              "(NG/PT/NC/O/2026/23780, July 2026).", bold_head="Patent pending:")
y = bullet(y, "three ArcGIS integrations shipped live in production (World Imagery, the 2014–2026 Wayback "
              "land-change archive, Sentinel-2 10 m land cover); Esri Startup Program application under "
              "review with the regional distributor engaged.", bold_head="Esri ecosystem:")
y = bullet(y, "AWS Activate credits awarded (2026); platform runs entirely on open-data satellite sources — "
              "no commercial imagery costs.", bold_head="Backed by AWS:")
y = bullet(y, "NSIA Prize for Innovation (NPI 4.0) and WFP Innovation Challenge applications in review; "
              "technical collaboration discussions with NASRDA, Nigeria's space agency.",
           bold_head="In review:")
y = bullet(y, "earlier systems include the Sentinel national OSINT/satellite monitoring engine and the "
              "Citadel conflict-prediction dashboard for Kebbi State — built and pitched to government, "
              "whose patterns EconomicBridge now productises at national scale.",
           bold_head="Track record:")

# ── How I work ─────────────────────────────────────────────────────────────
y = section(y, "HOW I WORK")
y = para(y, "Honesty as engineering discipline: my dashboards label modelled data as modelled, historical "
            "rows as historical, and reference imagery as \"not detection-time\". Confidence scores are "
            "published, not inflated; every model prediction routes to a human before action. In a market of "
            "overpromised satellite products, I sell what the physics supports — and governments can verify "
            "every sentence in the room, live.", size=9.2)
y = para(y, "Speed with proof: idea to production in days, never at the cost of a test suite, a provenance "
            "trail, or a runbook. The platform deploys through CI/CD, survives restore drills, and is "
            "measured by external monitors — because institutions buy systems, not demos.", size=9.2)

# ── Footer ─────────────────────────────────────────────────────────────────
c.setFillColor(MUTED)
c.setFont(BODY, 7.6)
c.drawCentredString((X0 + X1) / 2, 34,
                    "Everything above is verifiable: platform live at economicbridge.org · patent file "
                    "NG/PT/NC/O/2026/23780 · Bizra Farms Integrated Nigeria Limited RC 1929412 · July 2026")

c.showPage()
c.save()
print("built", OUT)
