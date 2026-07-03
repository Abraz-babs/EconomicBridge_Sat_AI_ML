"""Generate the NSIA Prize for Innovation Business Deck — landscape A4 slides,
house green branding. Business-first: problem, live product proof, market,
revenue model, go-to-market, team, use of funds.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nsia_deck.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

HERE = Path(__file__).parent
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")
OUT = Path(r"C:\Users\HP\Downloads\EconomicBridge_NSIA_Business_Deck.pdf")

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
ROW_ALT = colors.HexColor("#f0f7f2")

BODY, BODY_B = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("EBBody", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyB", r"C:\Windows\Fonts\arialbd.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyI", r"C:\Windows\Fonts\ariali.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyBI", r"C:\Windows\Fonts\arialbi.ttf"))
    pdfmetrics.registerFontFamily("EBBody", normal="EBBody", bold="EBBodyB",
                                  italic="EBBodyI", boldItalic="EBBodyBI")
    BODY, BODY_B = "EBBody", "EBBodyB"
except Exception:  # noqa: BLE001
    pass


def st(name, **kw):
    base = dict(fontName=BODY, fontSize=12, leading=17, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S_TITLE = st("t", fontName=BODY_B, fontSize=34, leading=40, textColor=DGREEN)
S_SUB = st("sub", fontSize=16, leading=22, textColor=MUTED)
S_H = st("h", fontName=BODY_B, fontSize=24, leading=29, textColor=DGREEN, spaceAfter=6)
S_P = st("p", spaceAfter=6)
S_BIG = st("big", fontName=BODY_B, fontSize=15, leading=21, textColor=INK)
S_LI = st("li", fontSize=12.5, leading=18.5, leftIndent=14, spaceAfter=4)
S_FOOT = st("foot", fontSize=9, leading=12, textColor=MUTED)
S_CELL = st("cell", fontSize=10.5, leading=14)
S_CELL_H = st("cellh", fontName=BODY_B, fontSize=10.5, leading=14, textColor=colors.white)


def bullet(text):
    return Paragraph(f"<font color='#1f8a3b'>•</font>&nbsp;&nbsp;{text}", S_LI)


def table(rows, widths=None):
    data = [[Paragraph(c, S_CELL_H if i == 0 else S_CELL) for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, hAlign="LEFT", colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DGREEN),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d8cd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for r in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def head(title):
    parts = []
    if LOGO.exists():
        img = Image(str(LOGO))
        img.drawHeight = 11 * mm * img.drawHeight / img.drawWidth
        img.drawWidth = 11 * mm
        img.hAlign = "LEFT"
        parts.append(img)
    parts += [Spacer(1, 2), Paragraph(title, S_H),
              HRFlowable(width="100%", thickness=1, color=GREEN, spaceAfter=8)]
    return parts


story = []

# ── Slide 1 — Title ─────────────────────────────────────────────────────────
if LOGO.exists():
    img = Image(str(LOGO))
    img.drawHeight = 22 * mm * img.drawHeight / img.drawWidth
    img.drawWidth = 22 * mm
    img.hAlign = "LEFT"
    story += [img]
story += [
    Spacer(1, 26),
    Paragraph("EconomicBridge", S_TITLE),
    Paragraph("Satellite intelligence for food security, farmland protection "
              "and disaster early-warning — live across Nigeria.", S_SUB),
    Spacer(1, 18),
    HRFlowable(width="40%", thickness=2, color=GREEN, hAlign="LEFT"),
    Spacer(1, 18),
    Paragraph("<b>Bizra Farms Integrated Nigeria Limited</b>", S_BIG),
    Paragraph("NSIA Prize for Innovation — Business Deck · July 2026", S_P),
    Spacer(1, 8),
    Paragraph("https://economicbridge.org &nbsp;·&nbsp; info@economicbridge.org "
              "&nbsp;·&nbsp; +234 703 791 9465 &nbsp;·&nbsp; Birnin Kebbi, Nigeria", S_P),
    PageBreak(),
]

# ── Slide 2 — Problem ───────────────────────────────────────────────────────
story += head("The problem: decisions without eyes")
story += [
    bullet("<b>Food insecurity at scale:</b> ~25 million Nigerians face acute food "
           "insecurity; agriculture is ~24% of GDP yet monitoring is manual and sparse."),
    bullet("<b>Farmland conflict:</b> farmer–herder encroachment destroys livelihoods; "
           "losses are estimated in billions of dollars annually, and states learn about "
           "incidents only after they happen."),
    bullet("<b>Slow disaster response:</b> floods and droughts are detected by field "
           "reports, days late — emergency agencies pre-position nothing."),
    bullet("<b>Blind aid targeting:</b> poverty maps used for aid allocation are "
           "census-based and years out of date."),
    Spacer(1, 8),
    Paragraph("Government agencies, states and aid partners all make high-stakes "
              "decisions with little or no current ground truth. The data exists — "
              "on satellites — but no Nigerian platform turns it into decisions.", S_BIG),
    PageBreak(),
]

# ── Slide 3 — Solution ──────────────────────────────────────────────────────
story += head("The solution: one platform, seven decisions")
story += [
    Paragraph("EconomicBridge fuses free, open satellite feeds into per-LGA "
              "decision intelligence for governments, agencies and aid partners:", S_P),
    Spacer(1, 4),
    table([
        ["Module", "Decision it powers"],
        ["Farmland Protection", "Encroachment & land-disturbance alerts, 48–72h conflict early-warning"],
        ["CropGuard", "Per-LGA crop health + AI leaf-photo disease diagnosis"],
        ["ShockGuard", "Flood & drought early-warning to disaster agencies"],
        ["Economic Visibility", "Satellite-calibrated poverty mapping for aid targeting"],
        ["Aid Coordination", "Who-gets-what tracking across partners"],
        ["Economic Mobility + SkillsBridge", "Livelihood and skills-gap intelligence"],
    ], widths=[72 * mm, 155 * mm]),
    Spacer(1, 6),
    Paragraph("Data: Copernicus Sentinel-1 SAR (~10 m, all-weather) · Sentinel-2 optical "
              "(10 m) · NASA FIRMS fire (~3 h) · VIIRS Black Marble night-lights (nightly) "
              "· WorldPop — all licensed for commercial use, with an in-app provenance "
              "panel that traces every indicator to its source scene.", S_FOOT),
    PageBreak(),
]

# ── Slide 4 — Traction / proof ──────────────────────────────────────────────
story += head("Not a prototype — live and verifiable today")
story += [
    table([
        ["Proof point", "Status (verifiable at economicbridge.org)"],
        ["Platform", "Live, HTTPS, multi-tenant, deployed on AWS (ECS/RDS, Terraform IaC)"],
        ["Coverage", "447/447 LGAs across our 10 pilot tenants (9 states + FCT) with live crop-health readings"],
        ["Farmland watch", "149 live per-LGA encroachment watches from Sentinel-1/2 fusion"],
        ["Trained AI", "ResNet-50 crop-disease model, 12 classes, 87% validation accuracy"],
        ["Agency alerts", "Automated English email digests to responsible agencies (e.g. NEMA)"],
        ["Provenance", "Every module traceable to satellite source, product and licence in-app"],
        ["Heritage", "Team previously deployed Citadel security dashboard for Kebbi State Govt"],
    ], widths=[55 * mm, 172 * mm]),
    Spacer(1, 6),
    Paragraph("Recognition pipeline: WFP Innovation Challenge 2026 (applied) · active "
              "collaboration discussions with NASRDA · beta-access letters issued to "
              "7 states + FCT.", S_P),
    PageBreak(),
]

# ── Slide 5 — Market ────────────────────────────────────────────────────────
story += head("Market: a growing EO-analytics wave, unserved locally")
story += [
    bullet("<b>Global:</b> Earth-Observation data & analytics ≈ <b>$4–5bn (2024)</b>, "
           "growing 15–20%/yr — fastest in downstream analytics, exactly our layer."),
    bullet("<b>Nigeria (serviceable):</b> 36 states + FCT, 15+ federal agencies and "
           "parastatals (NEMA, NASRDA, NALDA, ministries), plus NGOs and donors — "
           "at our tier pricing a realistic Nigerian market of <b>$5–15m/yr</b>."),
    bullet("<b>ECOWAS expansion:</b> 15 countries with the same food-security and "
           "disaster-response mandates and almost no sovereign EO capability."),
    bullet("<b>Wedge:</b> international vendors charge $100k–$1m/yr per ministry and "
           "offer single-purpose tools; we are local-first, multi-module and 30–70% "
           "cheaper, with Nigerian data-sovereignty (NDPA 2023) built in."),
    PageBreak(),
]

# ── Slide 6 — Business model ────────────────────────────────────────────────
story += head("Business model: tiered government SaaS")
story += [
    table([
        ["Tier", "Scope", "USD / year"],
        ["State Starter", "1 state · 2 modules · 5 seats", "$15,000"],
        ["State Professional", "1 state · all 7 modules · reports & exports", "$36,000"],
        ["Agency / Parastatal", "Duty-scoped modules across all pilot states", "$60,000"],
        ["Federal Enterprise", "Nationwide · all modules · API · SLA", "$150,000–300,000"],
        ["ECOWAS Country", "Full-country deployment", "from $100,000"],
    ], widths=[52 * mm, 118 * mm, 57 * mm]),
    Spacer(1, 6),
    bullet("<b>Add-ons:</b> per-indicator API feeds ($12k/yr) · agency alert "
           "subscriptions ($6k/yr) · bespoke assessments ($2.5–10k) · services $800/day."),
    bullet("<b>Donor-funded deployments</b> (WFP / World Bank programs): $80–150k per "
           "program + 20% annual O&M — non-dilutive scaling."),
    bullet("<b>Unit economics:</b> open-data ingestion keeps direct delivery cost low — "
           "target 65–80% net margin on subscriptions."),
    PageBreak(),
]

# ── Slide 7 — Go-to-market ──────────────────────────────────────────────────
story += head("Go-to-market: public–private partnership first")
story += [
    bullet("<b>Anchor PPP:</b> partner with a federal institution (discussions ongoing "
           "with NASRDA) for market access and endorsement, under a transparent, "
           "institutional revenue-share framework (ICRC/BPP-compliant)."),
    bullet("<b>State pilots → paid licences:</b> beta access already extended to Kebbi, "
           "Kaduna, Niger, Plateau, Benue, Zamfara, Nasarawa, FCT and others; pilots "
           "convert at 25% of tier price, creditable to year-1."),
    bullet("<b>Duty-scoped agency sales:</b> each agency buys only the modules matching "
           "its mandate (NEMA → ShockGuard; agriculture → CropGuard + Farmland) — "
           "small first ticket, natural upsell."),
    bullet("<b>Donor channel:</b> WFP Innovation Challenge application submitted; the "
           "same deployments qualify for World Bank / EU resilience programs."),
    PageBreak(),
]

# ── Slide 8 — Competitive edge ──────────────────────────────────────────────
story += head("Why we win")
story += [
    table([
        ["", "International EO vendors", "EconomicBridge"],
        ["Price", "$100k–$1m/yr, single ministry", "$15k–$300k/yr, whole-government tiers"],
        ["Breadth", "Single-purpose (crop OR flood)", "7 modules on one multi-tenant platform"],
        ["Locality", "Remote support, foreign data custody", "Nigerian company, NDPA 2023, local support"],
        ["Granularity", "National / state dashboards", "Per-LGA (774-ready), village-level alerts"],
        ["Transparency", "Black-box scores", "In-app provenance for every indicator"],
    ], widths=[35 * mm, 90 * mm, 102 * mm]),
    Spacer(1, 6),
    Paragraph("Defensibility: per-LGA satellite baselines and ground-truth accumulating "
              "from day one of live operation, locally trained models, and government "
              "relationships — the data moat deepens with every revisit cycle.", S_P),
    PageBreak(),
]

# ── Slide 9 — Team ──────────────────────────────────────────────────────────
story += head("Team & operator")
story += [
    Paragraph("<b>Abdullahi Zuru Ibrahim</b> — Founder & CEO", S_BIG),
    bullet("Built and operates the full EconomicBridge platform: satellite ingestion, "
           "ML models, cloud infrastructure and go-to-market."),
    bullet("Previously delivered <b>Citadel</b>, the Kebbi State security dashboard "
           "(satellite + AI conflict prediction) — deployed for state government use."),
    bullet("Operator of record: <b>Bizra Farms Integrated Nigeria Limited</b> (CAC-registered), "
           "an agribusiness with working farms — the platform is built by people who "
           "farm, for decisions that reach farmers."),
    Spacer(1, 8),
    Paragraph("Advisory & partnerships in motion: NASRDA (space agency) collaboration "
              "discussions; state agriculture and emergency-management contacts across "
              "the pilot states.", S_P),
    PageBreak(),
]

# ── Slide 10 — Use of funds / roadmap ───────────────────────────────────────
story += head("What the NSIA Prize unlocks")
story += [
    table([
        ["Investment area", "Outcome (12 months)"],
        ["Cloud & ingestion scale-up (30%)", "All 36 states + FCT live (774 LGAs), daily feeds, production hardening"],
        ["Model training (25%)", "U-Net flood-extent model + expanded crop-disease classes, SHAP explainability"],
        ["Farmer reach (20%)", "Multilingual SMS alerts (Hausa, Yoruba, Igbo, Fulfulde) via free-tier agency channel"],
        ["Sales & partnerships (15%)", "PPP definitive agreement, 3 paid state licences, 2 agency subscriptions"],
        ["Compliance & audit (10%)", "SOC-style audit package, NDPA certification, ISO-aligned processes"],
    ], widths=[75 * mm, 152 * mm]),
    Spacer(1, 8),
    Paragraph("The platform is built and live; the prize converts it into a national "
              "capability — Nigerian satellite intelligence, serving Nigerian decisions, "
              "commercially sustainable from year one.", S_BIG),
    Spacer(1, 10),
    Paragraph("Abdullahi Zuru Ibrahim · Bizra Farms Integrated Nigeria Ltd · "
              "https://economicbridge.org · info@economicbridge.org · +234 703 791 9465", S_FOOT),
]

doc = SimpleDocTemplate(
    str(OUT), pagesize=landscape(A4),
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=14 * mm, bottomMargin=12 * mm,
    title="EconomicBridge — NSIA Business Deck",
    author="Bizra Farms Integrated Nigeria Ltd",
)
doc.build(story)
print(f"built {OUT}")
