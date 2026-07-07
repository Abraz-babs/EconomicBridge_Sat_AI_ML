"""One-page EconomicBridge System Architecture diagram (for the Esri Startup
Program 'product architecture' submission). Branded, portrait A4.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_architecture.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\HP\Downloads\EconomicBridge_Architecture.pdf")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
TINT = colors.HexColor("#f0f7f2")
ESRI = colors.HexColor("#0079c1")
ESRI_TINT = colors.HexColor("#eaf4fb")
CHIP = colors.HexColor("#e7f0ea")

BODY, BODY_B = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("EB", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBB", r"C:\Windows\Fonts\arialbd.ttf"))
    BODY, BODY_B = "EB", "EBB"
except Exception:  # noqa: BLE001
    pass

W, H = A4
c = canvas.Canvas(str(OUT), pagesize=A4)
X0, X1 = 34, W - 34


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


def arrow(cx, y1, y2):
    c.setStrokeColor(MUTED)
    c.setLineWidth(1.3)
    c.line(cx, y1, cx, y2)
    c.setFillColor(MUTED)
    c.setStrokeColor(MUTED)
    p = c.beginPath()
    p.moveTo(cx, y2)
    p.lineTo(cx - 4, y2 + 6)
    p.lineTo(cx + 4, y2 + 6)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def chips(items, top, bottom, accent):
    n = len(items)
    gap = 8
    usable = (X1 - X0) - 16 - gap * (n - 1)
    cw = usable / n
    x = X0 + 8
    cy_top, cy_bot = top - 4, bottom + 6
    for it in items:
        c.setFillColor(colors.white if accent == ESRI else CHIP)
        c.setStrokeColor(accent)
        c.setLineWidth(1)
        c.roundRect(x, cy_bot, cw, cy_top - cy_bot, 5, stroke=1, fill=1)
        parts = it.split("\n")
        c.setFillColor(INK)
        th = len(parts) * 10
        ty = (cy_top + cy_bot) / 2 + th / 2 - 8
        for i, part in enumerate(parts):
            c.setFont(BODY_B if i == 0 else BODY, 8.2 if i == 0 else 7.4)
            c.drawCentredString(x + cw / 2, ty - i * 10, part)
        x += cw + gap


def layer(top, height, title, kind, content, accent=GREEN, tint=TINT):
    bottom = top - height
    c.setFillColor(tint)
    c.setStrokeColor(accent)
    c.setLineWidth(1.6 if accent == ESRI else 1.1)
    c.roundRect(X0, bottom, X1 - X0, height, 7, stroke=1, fill=1)
    c.setFillColor(ESRI if accent == ESRI else DGREEN)
    c.setFont(BODY_B, 10)
    c.drawString(X0 + 10, top - 15, title)
    if kind == "line":
        c.setFillColor(INK)
        c.setFont(BODY, 8.8)
        lines = wrap(content, BODY, 8.8, X1 - X0 - 20)
        ty = top - 30
        for ln in lines:
            c.drawString(X0 + 10, ty, ln)
            ty -= 12
    elif kind == "chips":
        chips(content, top - 20, bottom, accent)
    return bottom


# ── Header ──────────────────────────────────────────────────────────────────
y = H - 40
if LOGO.exists():
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(str(LOGO))
        iw, ih = ir.getSize()
        c.drawImage(ir, X0, y - 6, width=42, height=42 * ih / iw, mask="auto")
    except Exception:  # noqa: BLE001
        pass
c.setFillColor(DGREEN)
c.setFont(BODY_B, 20)
c.drawString(X0 + 50, y + 14, "EconomicBridge — System Architecture")
c.setFillColor(MUTED)
c.setFont(BODY, 9.5)
c.drawString(X0 + 50, y, "Satellite Earth-observation intelligence for African governments · "
                        "operated by Bizra Farms Integrated Nigeria Ltd")

# ── Layered stack ───────────────────────────────────────────────────────────
cursor = H - 108
GAP = 20

SRC = ["Sentinel-1\nSAR (10 m)", "Sentinel-2\nNDVI (10 m)", "NASA FIRMS\n(thermal/fire)",
       "NASA VIIRS\n(night-lights)", "WorldPop\n(population)"]
ARC = ["ArcGIS Online\nhosted feature layers", "ArcGIS Location Platform\nbasemaps · geocoding",
       "ArcGIS Image\nsub-field NDVI zonal maps", "ArcGIS Marketplace\ngov / NGO distribution"]

specs = [
    (64, "OPEN SATELLITE DATA SOURCES  (free, commercial-licensed)", "chips", SRC, GREEN, TINT),
    (46, "INGESTION & PROCESSING   ·   AWS ECS Fargate", "line",
     "Per-LGA aggregation · per-pixel cloud masking · multi-sensor fusion · Copernicus "
     "Statistical API (rate-limited, budgeted)", GREEN, TINT),
    (56, "INTELLIGENCE & DATA   ·   AWS RDS PostgreSQL + PostGIS  (schema-per-tenant)", "line",
     "Trained ResNet-50 crop-disease model · SAR / NDVI anomaly & stress detectors · "
     "data-provenance trail · isolated per-tenant workspaces", GREEN, TINT),
    (56, "APPLICATION   ·   AWS ECS Fargate + Application Load Balancer", "line",
     "FastAPI microservices (API / ingestion / ML) · Next.js web dashboard · 7 modules: "
     "Farmland, CropGuard, ShockGuard, Poverty, Aid, Mobility, Skills", GREEN, TINT),
    (46, "DELIVERY", "line",
     "Per-LGA interactive dashboard · Farm Check (single + bulk) + CSV export · automated "
     "agency email alerts · leaf-photo AI diagnosis", GREEN, TINT),
    (66, "ARCGIS INTEGRATION   (partnership roadmap — where Esri plugs in)", "chips", ARC, ESRI, ESRI_TINT),
]

for i, (h, title, kind, content, accent, tint) in enumerate(specs):
    bottom = layer(cursor, h, title, kind, content, accent, tint)
    if i < len(specs) - 1:
        arrow((X0 + X1) / 2, bottom, bottom - GAP + 1)
    cursor = bottom - GAP

# ── Cross-cutting footer band ───────────────────────────────────────────────
band_top = cursor - 4
c.setFillColor(colors.HexColor("#0a5c2e"))
c.roundRect(X0, band_top - 26, X1 - X0, 26, 5, stroke=0, fill=1)
c.setFillColor(colors.white)
c.setFont(BODY, 7.6)
c.drawCentredString((X0 + X1) / 2, band_top - 17,
                    "Cross-cutting:  Terraform IaC  ·  CI/CD (GitHub Actions OIDC)  ·  "
                    "multi-tenant schema isolation  ·  NDPA-2023 compliant  ·  live at economicbridge.org")

c.setFillColor(MUTED)
c.setFont(BODY, 8)
c.drawCentredString((X0 + X1) / 2, band_top - 44,
                    "Data flows top-to-bottom: open satellite feeds → AWS ingestion/ML → per-LGA "
                    "intelligence → delivery, with ArcGIS as the partnership delivery + distribution layer.")
c.setFont(BODY, 8)
c.drawCentredString((X0 + X1) / 2, band_top - 58,
                    "Abdullahi Zuru Ibrahim · Founder & CEO · https://economicbridge.org · bizra@economicbridge.org")

c.showPage()
c.save()
print("built", OUT)
