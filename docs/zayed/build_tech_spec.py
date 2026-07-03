"""Generate the Zayed-submission Technical Specification PDF (2 pages).

Run from repo root with the api venv (reportlab installed):
    apps/api/.venv/Scripts/python.exe docs/zayed/build_tech_spec.py
Output: docs/zayed/EconomicBridge_Technical_Specification.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

GREEN = colors.HexColor("#044d2a")
ACCENT = colors.HexColor("#078a46")
GOLD = colors.HexColor("#b8860b")
INK = colors.HexColor("#1d2520")

OUT = Path(__file__).parent / "EconomicBridge_Technical_Specification.pdf"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=20, textColor=GREEN,
                    spaceAfter=2, alignment=0)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=10.5,
                     textColor=colors.HexColor("#555555"), spaceAfter=10)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5,
                    textColor=GREEN, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9.3, leading=12.6,
                      textColor=INK)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.6, leading=11)
# Header cells are Paragraphs, so the white must live in the STYLE — the
# TableStyle TEXTCOLOR only affects plain strings.
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold",
                       textColor=colors.white)
FOOT = ParagraphStyle("FOOT", parent=ss["Normal"], fontSize=8,
                      textColor=colors.HexColor("#666666"))

TBL_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), GREEN),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8.6),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
     [colors.white, colors.HexColor("#f2f7f3")]),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
])


def t(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[Paragraph(c, CELLB if i == 0 else CELL) for c in row]
            for i, row in enumerate(rows)]
    tbl = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    tbl.setStyle(TBL_STYLE)
    return tbl


story = [
    Paragraph("EconomicBridge — Technical Specification", H1),
    Paragraph(
        "AI &amp; Satellite Intelligence for Agriculture, Food Security &amp; "
        "Aid Delivery · Operated by Bizra Farms Integrated Nigeria Limited", SUB),

    Paragraph(
        "EconomicBridge is a deployed, multi-tenant satellite-intelligence "
        "platform serving West African governments, NGOs, and international "
        "bodies. It is designed for 52 administrative units (36 Nigerian "
        "states + FCT + 15 ECOWAS countries) with 10 pilot tenants live "
        "today, spanning over 700 LGAs/districts across Nigeria, Ghana and "
        "Senegal. Seven intelligence modules convert satellite and open "
        "statistical data into 24–72-hour early warnings and decision-grade "
        "reporting. The dashboard is open-access for situational awareness; "
        "institutional features are invite-gated per tenant.", BODY),

    Paragraph("Platform architecture", H2),
    Paragraph(
        "Five containerized microservices — Next.js 16 dashboard, FastAPI "
        "core API, satellite-ingestion service, ML inference service, and a "
        "notifications service — run on AWS ECS Fargate (eu-west-1) behind a "
        "path-routing Application Load Balancer. PostgreSQL 16 (RDS) holds a "
        "schema-per-tenant data model; ElastiCache Redis provides caching; "
        "model artifacts ship via S3; credentials live exclusively in AWS "
        "Secrets Manager. The entire stack — 140+ resources — is defined in "
        "Terraform, and CI/CD runs on GitHub Actions with OIDC federation "
        "(no long-lived cloud keys anywhere).", BODY),

    Paragraph("Intelligence modules", H2),
    t([
        ["Module", "Function", "Primary inputs"],
        ["Economic Visibility", "Poverty &amp; settlement mapping per LGA",
         "WorldPop, nightlights, DHS-style indicators"],
        ["Aid Coordination", "Coverage gaps and duplication across agencies",
         "HDX HAPI, partner records, bulk CSV"],
        ["Farmland Protection", "Encroachment &amp; conflict early warning "
         "(24–72 h)", "Sentinel-1 SAR, NASA FIRMS, ML conflict model"],
        ["CropGuard", "Crop-disease diagnosis + vegetation &amp; price "
         "intelligence", "Leaf imagery (ResNet-50), Sentinel-2 NDVI, market prices"],
        ["ShockGuard", "Flood / drought detection and alerting",
         "Sentinel-1 SAR series, statistical detectors"],
        ["Mobility Compass", "Income &amp; cost-of-living, displacement capacity",
         "World Bank GNI/employment (USD-anchored, dual-currency)"],
        ["SkillsBridge", "Education access &amp; connectivity targeting",
         "UNICEF GIGA school locations, World Bank ICT"],
    ], [38, 64, 68]),

    Paragraph("Live data feeds (running in production)", H2),
    t([
        ["Source", "Data", "Cadence"],
        ["Copernicus Sentinel-1 (CDSE)", "SAR backscatter — all-weather flood/"
         "change signal", "Weekly per tenant ROI"],
        ["Copernicus Sentinel-2 (CDSE)", "NDVI — crop vigor &amp; anomaly", "Weekly"],
        ["NASA FIRMS", "MODIS/VIIRS active-fire detections", "Daily 06:00 UTC"],
        ["N2YO", "Live satellite pass tracking", "Every 15 minutes"],
        ["World Bank API", "GNI/capita, employment (CC BY 4.0)", "Monthly"],
        ["UNICEF GIGA", "School locations (100k+ for Nigeria)", "Monthly"],
        ["WorldPop", "Gridded population", "Weekly"],
    ], [52, 78, 40]),
    Paragraph(
        "Every datum carries provenance: dashboards badge LIVE observations "
        "distinctly from MODELLED baselines — the platform never presents "
        "synthetic data as measured.", BODY),

    Paragraph("AI / ML models", H2),
    t([
        ["Model", "Purpose", "Status"],
        ["ResNet-50 (12-class)", "Crop-disease classification from leaf "
         "imagery; top-k output, confidence bands, human-review gating",
         "Fine-tuned; 87.2% validation accuracy; serving in production"],
        ["Random Forest", "Conflict prediction 24–72 h (lineage: our earlier "
         "state security-intelligence build)", "Proven pattern, retrained per pilot"],
        ["Statistical detectors", "Flood (SAR z-scores) and NDVI anomaly on "
         "live Sentinel series", "Running on live Copernicus data"],
    ], [40, 78, 52]),

    Paragraph("Security, tenancy &amp; compliance", H2),
    Paragraph(
        "JWT authentication (15-minute access / 7-day revocable refresh, "
        "bcrypt password storage) with per-IP login rate-limiting. Strict "
        "multi-tenant isolation: schema-per-tenant in PostgreSQL plus "
        "request-level permitted-tenant enforcement — a state tenant can "
        "never read another state's data (HTTP 403), while accredited "
        "regional bodies (e.g., ECOWAS-type partners) hold read access "
        "across pilots. Personally identifiable data sits behind a signed "
        "Data-Processing-Agreement gate; the audit log is INSERT-only. "
        "Farmer inclusion is registration-free: phone numbers are sourced "
        "through partner agencies acting as data controllers (NDPA 2023 "
        "aligned), with multilingual SMS alerts (English, French, Portuguese "
        "live; Hausa, Yoruba, Igbo drafted pending native review).", BODY),

    Paragraph("Operations", H2),
    Paragraph(
        "Scheduled ingestion (8 jobs, manually fireable from the admin "
        "console), CloudWatch logging and alarms, automated monthly/quarterly "
        "PDF &amp; CSV reporting via EventBridge Scheduler, and a mock-to-live "
        "gateway pattern for outbound channels (AWS SES email, AWS SNS SMS) "
        "so every integration can be exercised safely before carrier "
        "activation.", BODY),

    Spacer(1, 6 * mm),
    Paragraph(
        "Live platform: http://economicbridge-staging-alb-691775567."
        "eu-west-1.elb.amazonaws.com &nbsp;·&nbsp; "
        "Source: github.com/Abraz-babs/EconomicBridge_Sat_AI_ML &nbsp;·&nbsp; "
        "Contact: bizrafarms@gmail.com · +234 703 791 9465 · Birnin Kebbi, "
        "Kebbi State, Nigeria", FOOT),
]

doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=16 * mm, rightMargin=16 * mm,
    topMargin=14 * mm, bottomMargin=14 * mm,
    title="EconomicBridge — Technical Specification",
    author="Bizra Farms Integrated Nigeria Limited",
)
doc.build(story)
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
