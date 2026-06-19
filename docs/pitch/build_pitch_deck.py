"""Generate the EconomicBridge investor pitch deck (16:9 PDF, Bizra branding).

    apps/api/.venv/Scripts/python.exe docs/pitch/build_pitch_deck.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas

LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")
OUT = Path(__file__).parent / "EconomicBridge_Pitch_Deck.pdf"

W, H = 960.0, 540.0  # 16:9
GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
BROWN = colors.HexColor("#6e2b2b")
GOLD = colors.HexColor("#e8a81a")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#6b6b6b")
LIGHT = colors.HexColor("#f3f7f4")

c = canvas.Canvas(str(OUT), pagesize=(W, H))


def wrap(text, font, size, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def chrome(page):
    c.setFillColor(colors.white)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(GREEN)
    c.rect(0, H - 8, W, 8, fill=1, stroke=0)
    c.setFillColor(GREY)
    c.setFont("Helvetica", 9)
    c.drawString(60, 22, "EconomicBridge  ·  Bizra Farms Integrated Nigeria Limited")
    c.drawRightString(W - 60, 22, str(page))


def title(text):
    c.setFillColor(DGREEN)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(60, H - 78, text)
    c.setFillColor(GOLD)
    c.rect(60, H - 92, 70, 4, fill=1, stroke=0)


def bullets(items, top=H - 140, size=16, gap=14, x=70, maxw=W - 150, lead=None):
    y = top
    if lead:
        c.setFillColor(INK)
        c.setFont("Helvetica-Oblique", 17)
        for ln in wrap(lead, "Helvetica-Oblique", 17, W - 150):
            c.drawString(60, y, ln)
            y -= 24
        y -= 12
    for it in items:
        c.setFillColor(GREEN)
        c.circle(x + 3, y + 5, 3.2, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica", size)
        first = True
        for ln in wrap(it, "Helvetica", size, maxw):
            c.drawString(x + 16, y, ln)
            y -= size + 6
            first = False
        y -= gap - 6


def stat_grid(stats, note=None):
    # 2x2 big-number grid (kept clear of the title underline at ~y=448)
    xs = [70, W / 2 + 10]
    ys = [H - 235, H - 375]
    ch = 120
    i = 0
    for ry in ys:
        for rx in xs:
            if i >= len(stats):
                break
            big, label = stats[i]
            c.setFillColor(LIGHT)
            c.roundRect(rx, ry, W / 2 - 90, ch, 10, fill=1, stroke=0)
            c.setFillColor(GREEN)
            c.setFont("Helvetica-Bold", 36)
            c.drawString(rx + 22, ry + 66, big)
            c.setFillColor(INK)
            c.setFont("Helvetica", 13)
            for k, ln in enumerate(wrap(label, "Helvetica", 13, W / 2 - 130)):
                c.drawString(rx + 22, ry + 42 - k * 16, ln)
            i += 1
    if note:
        c.setFillColor(GREY)
        c.setFont("Helvetica-Oblique", 12)
        c.drawString(60, 52, note)


# ── Slide 1 — Cover ───────────────────────────────────────────────────────
chrome(1)
try:
    from reportlab.lib.utils import ImageReader
    img = ImageReader(str(LOGO))
    iw, ih = 360, 360 * 390 / 1024
    c.drawImage(img, (W - iw) / 2, H - 200, width=iw, height=ih, mask="auto")
except Exception:
    pass
c.setFillColor(DGREEN)
c.setFont("Helvetica-Bold", 46)
c.drawCentredString(W / 2, H - 270, "EconomicBridge")
c.setFillColor(INK)
c.setFont("Helvetica", 18)
c.drawCentredString(W / 2, H - 300, "AI & Satellite Intelligence for Agriculture, Food Security & Aid")
c.setFillColor(GREY)
c.setFont("Helvetica", 13)
c.drawCentredString(W / 2, H - 340, "Operated by Bizra Farms Integrated Nigeria Limited")
c.setFillColor(GREEN)
c.setFont("Helvetica-Bold", 13)
c.drawCentredString(W / 2, H - 372, "Live platform  ·  bizrafarms@gmail.com  ·  +234 703 791 9465")
c.setFillColor(GREY)
c.setFont("Helvetica-Oblique", 12)
c.drawCentredString(W / 2, 70, "Seaside Startup Summit Armenia 2026")
c.showPage()

# ── Slide 2 — Problem ─────────────────────────────────────────────────────
chrome(2)
title("The Problem")
bullets([
    "Across West Africa, smallholder farmers lose crops, land and livelihoods "
    "to floods, drought, crop disease and conflict, season after season.",
    "Governments and aid agencies respond almost blind: data is national, "
    "months out of date, and disconnected from what is happening on the ground.",
    "Every disaster leaves a signal in the soil, water and heat long before it "
    "strikes, but no one is reading those signals in time.",
    "The result: preventable losses, misdirected aid, and lives at risk.",
], lead="Hundreds of millions depend on smallholder farming. Much of the loss is preventable.")
c.showPage()

# ── Slide 3 — Solution ────────────────────────────────────────────────────
chrome(3)
title("The Solution")
bullets([
    "EconomicBridge turns live earth-observation data into early warning and "
    "decision support, at local-government-level granularity.",
    "One platform gives governments, NGOs and regional bodies a real-time "
    "picture: forecast, reality on the ground, and who is affected.",
    "Detect crop disease, flood and drought, and predict conflict 24 to 72 "
    "hours ahead, then deliver the alert to the people who need it.",
], lead="A satellite-and-AI early-warning system for the people who feed the continent.")
c.showPage()

# ── Slide 4 — Product ─────────────────────────────────────────────────────
chrome(4)
title("One platform, seven intelligence modules")
bullets([
    "CropGuard: AI crop-disease diagnosis from a leaf photo + satellite vegetation health",
    "ShockGuard: flood and drought detection from all-weather satellite radar",
    "Farmland Protection: conflict and encroachment early warning (24-72h)",
    "Economic Visibility: poverty and settlement mapping from satellite data",
    "Mobility Compass: income and cost-of-living intelligence",
    "SkillsBridge: education access and connectivity mapping",
    "Aid Coordination: agency coverage and gap mapping",
], top=H - 130, size=15, gap=10)
c.showPage()

# ── Slide 5 — How it works ────────────────────────────────────────────────
chrome(5)
title("Built on live, authoritative data")
bullets([
    "Copernicus Sentinel-1 (radar) and Sentinel-2 (vegetation/NDVI)",
    "NASA FIRMS active-fire detections and VIIRS night-lights",
    "World Bank economics, UNICEF GIGA schools, WorldPop population grids",
    "AI: a ResNet-50 crop classifier (87% validation), conflict prediction, "
    "and SAR / NDVI anomaly detection",
    "Honest provenance: live observations are always labelled distinctly from "
    "modelled baselines, so decision-makers trust what they see.",
])
c.showPage()

# ── Slide 6 — Live & working (traction proof) ─────────────────────────────
chrome(6)
title("Live in production, not a prototype")
stat_grid([
    ("700+", "Local government areas / districts covered across Nigeria, Ghana and Senegal"),
    ("7", "Live satellite and economic data feeds, self-scheduled daily/weekly"),
    ("87.2%", "Validation accuracy of our trained ResNet-50 crop-disease model"),
    ("5", "Microservices on AWS with CI/CD and multi-tenant data isolation"),
], note="Designed to scale to 52 administrative units: 36 Nigerian states + FCT + 15 ECOWAS countries.")
c.showPage()

# ── Slide 7 — Inclusion & impact ──────────────────────────────────────────
chrome(7)
title("Reaching the last mile")
bullets([
    "Farmers need no smartphone, no app and no literacy: alerts arrive as a "
    "simple SMS.",
    "Multilingual by design: English, French and Portuguese live; Hausa, "
    "Yoruba and Igbo in preparation.",
    "Delivered through trusted partner agencies, registration-free and privacy-first.",
    "24 to 72 hours of early warning means time to act: protect a harvest, "
    "move livestock, evacuate, or pre-position aid.",
], lead="Technology only matters if it reaches the person in the field.")
c.showPage()

# ── Slide 8 — Market ──────────────────────────────────────────────────────
chrome(8)
title("Market")
bullets([
    "Immediate market: 36 Nigerian states + FCT, plus 15 ECOWAS member states "
    "(52 administrative tenants).",
    "Buyers: state governments, federal agencies (disaster, agriculture), NGOs, "
    "and regional bodies such as ECOWAS.",
    "Tailwind: climate-adaptation and food-security funding is scaling fast "
    "across Africa.",
    "Expansion path: the same platform template extends across Sub-Saharan "
    "Africa, one tenant at a time.",
])
c.showPage()

# ── Slide 9 — Business model ──────────────────────────────────────────────
chrome(9)
title("Business Model")
bullets([
    "SaaS subscription per government / agency tenant: a free pilot converts to "
    "an annual licence.",
    "Tiered by modules and by coverage (per-state, federal, and regional "
    "licensing).",
    "Premium automated reports and data exports.",
    "Farmer SMS stays free at the point of use, funded by institutional "
    "subscriptions and donor programmes: impact and revenue aligned.",
])
c.showPage()

# ── Slide 10 — Traction & go-to-market ────────────────────────────────────
chrome(10)
title("Traction & Momentum")
bullets([
    "Platform live on AWS with multi-tenant onboarding ready today.",
    "Active outreach underway to state governments, NEMA and the ECOWAS "
    "Commission (formal proposals delivered).",
    "Inbound interest from a serving State Commissioner; first beta onboarding "
    "in progress.",
    "Submitted to the Zayed Sustainability Prize and the WFP Innovation "
    "Challenge.",
], lead="Built first, selling now: the product is done, the conversations are open.")
c.showPage()

# ── Slide 11 — Team ───────────────────────────────────────────────────────
chrome(11)
title("Team")
bullets([
    "Abdullahi Zuru Ibrahim, Founder & CEO: product vision, partnerships, and "
    "an AI-native build that shipped a full production platform lean.",
    "Operated by Bizra Farms Integrated Nigeria Limited.",
    "Seeking: technical, agronomy and go-to-market partners to scale across "
    "West Africa.",
], lead="A lean, execution-first team that turned an idea into a live platform.")
c.showPage()

# ── Slide 12 — Ask & vision ───────────────────────────────────────────────
chrome(12)
title("The Ask")
bullets([
    "We are seeking investment, mentorship and partnerships, and the network "
    "this summit convenes.",
    "Use of funds: field pilots with partner agencies, team, and go-to-market "
    "across Nigeria and ECOWAS.",
    "Together we can make early warning the default, not the exception.",
], lead="Vision: every farmer visible, every harvest protected, every life seen in time.")
c.setFillColor(DGREEN)
c.setFont("Helvetica-Bold", 16)
c.drawString(60, 96, "EconomicBridge  ·  Planting the seeds of tomorrow")
c.setFillColor(GREY)
c.setFont("Helvetica", 12)
c.drawString(60, 74, "bizrafarms@gmail.com   ·   +234 703 791 9465")
c.showPage()

c.save()
shutil.copy(OUT, Path(r"C:\Users\HP\Downloads") / OUT.name)
print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes, 12 slides); copied to Downloads")
