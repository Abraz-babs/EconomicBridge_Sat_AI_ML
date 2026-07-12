"""SLA + DPA one-pagers for institutional customers (A+ plan, Pillar 3
'paper the promises'). Two PDFs: EconomicBridge_SLA.pdf and
EconomicBridge_DPA.pdf — templates executed as schedules to the master
agreement / MOU from the commercial pack; legal review recommended.

    apps/api/.venv/Scripts/python.exe docs/company/build_sla_dpa.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT_SLA = Path(r"C:\Users\HP\Downloads\EconomicBridge_SLA.pdf")
OUT_DPA = Path(r"C:\Users\HP\Downloads\EconomicBridge_DPA.pdf")
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
X0, X1 = 42, W - 42


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


class Doc:
    """Tiny flowing-canvas helper with page-break guard."""

    def __init__(self, path: Path, title: str, sub: str):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.title, self.sub = title, sub
        self.page = 0
        self._new_page()

    def _new_page(self):
        if self.page > 0:
            self._footer()
            self.c.showPage()
        self.page += 1
        y = H - 46
        if self.page == 1 and LOGO.exists():
            try:
                from reportlab.lib.utils import ImageReader
                ir = ImageReader(str(LOGO))
                iw, ih = ir.getSize()
                self.c.drawImage(ir, X0, y - 8, width=36, height=36 * ih / iw, mask="auto")
            except Exception:  # noqa: BLE001
                pass
        self.c.setFillColor(DGREEN)
        self.c.setFont(BODY_B, 14.5 if self.page == 1 else 11)
        self.c.drawString(X0 + (44 if self.page == 1 else 0), y + (8 if self.page == 1 else 0),
                          self.title if self.page == 1 else f"{self.title} (continued)")
        if self.page == 1:
            self.c.setFillColor(MUTED)
            self.c.setFont(BODY, 8.6)
            self.c.drawString(X0 + 44, y - 6, self.sub)
        self.y = y - 30

    def _footer(self):
        self.c.setFillColor(MUTED)
        self.c.setFont(BODY, 7.2)
        self.c.drawCentredString((X0 + X1) / 2, 28,
                                 "Bizra Farms Integrated Nigeria Limited (RC 1929412) · EconomicBridge · "
                                 "template — execute as a schedule to the master agreement; obtain legal review · "
                                 f"v1.0 · 12 July 2026 · p. {self.page}")

    def guard(self, need=70):
        if self.y < need:
            self._new_page()

    def section(self, label):
        self.guard(95)
        self.c.setFillColor(TINT)
        self.c.setStrokeColor(GREEN)
        self.c.setLineWidth(0.8)
        self.c.roundRect(X0, self.y - 16, X1 - X0, 19, 4, stroke=1, fill=1)
        self.c.setFillColor(DGREEN)
        self.c.setFont(BODY_B, 9.6)
        self.c.drawString(X0 + 7, self.y - 10.5, label)
        self.y -= 28

    def para(self, text, size=8.7, leading=11.4, bold_head=None):
        self.guard()
        maxw = X1 - X0
        full = (bold_head + " " + text) if bold_head else text
        lines = wrap(self.c, full, BODY, size, maxw)
        for i, ln in enumerate(lines):
            self.guard()
            if i == 0 and bold_head:
                self.c.setFont(BODY_B, size)
                self.c.setFillColor(INK)
                self.c.drawString(X0, self.y, bold_head)
                off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
                self.c.setFont(BODY, size)
                self.c.drawString(X0 + off, self.y, ln[len(bold_head):].lstrip())
            else:
                self.c.setFont(BODY, size)
                self.c.setFillColor(INK)
                self.c.drawString(X0, self.y, ln)
            self.y -= leading
        self.y -= 3

    def row(self, cols, widths, bold=False, size=8.5):
        self.guard()
        x = X0
        self.c.setFont(BODY_B if bold else BODY, size)
        self.c.setFillColor(MUTED if bold else INK)
        for text, wd in zip(cols, widths):
            for j, ln in enumerate(wrap(self.c, text, BODY_B if bold else BODY, size, wd - 6)):
                self.c.drawString(x, self.y - j * 10.5, ln)
            x += wd
        self.y -= 13 + 10.5 * max(
            (len(wrap(self.c, t, BODY_B if bold else BODY, size, wd - 6)) - 1)
            for t, wd in zip(cols, widths)
        )

    def save(self):
        self._footer()
        self.c.showPage()
        self.c.save()


# ═════════════════ SLA ═════════════════
d = Doc(OUT_SLA, "EconomicBridge — Service Level Agreement (SLA)",
        "Schedule to the Master Services Agreement between Bizra Farms Integrated Nigeria Limited and the Customer")

d.section("1. SERVICE")
d.para("EconomicBridge, the satellite Earth-observation decision-intelligence platform operated by Bizra Farms "
       "Integrated Nigeria Limited and delivered as software-as-a-service at https://economicbridge.org, comprising "
       "the Customer's isolated tenant workspace, the modules licensed in the Order, satellite-derived data feeds, "
       "alerting, and per-coordinate field tools.")

d.section("2. AVAILABILITY COMMITMENT")
d.para("The Provider commits to Monthly Platform Uptime of at least 99.5%. Monthly Platform Uptime = "
       "(total minutes in the calendar month − Downtime minutes) ÷ total minutes × 100, measured by the Provider's "
       "independent external monitoring of the production endpoints, records available to the Customer on request.",
       bold_head="2.1 Target.")
d.para("Downtime excludes: (a) scheduled maintenance notified at least 48 hours in advance and targeted outside "
       "West Africa business hours, capped at 4 hours per month; (b) faults of the Customer's own networks, devices "
       "or credentials; (c) force majeure; (d) suspension for material breach or non-payment.",
       bold_head="2.2 Exclusions.")
d.para("Platform availability is distinct from satellite acquisition. Upstream imagery (Copernicus Sentinel-1/2, "
       "NASA FIRMS/VIIRS and similar) follows the providers' orbital revisit cycles (typically 1–6 days) and, for "
       "optical sensors, cloud conditions. The Provider commits to ingesting and processing new scenes into the "
       "platform within 24 hours of their public availability, and states data recency transparently in-product. "
       "No commitment is made, by any vendor honestly, to the timing of satellite passes or cloud-free skies.",
       bold_head="2.3 Data freshness (honest scope).")

d.section("3. SUPPORT")
d.para("Channel: bizra@economicbridge.org. Hours: Monday–Friday, 08:00–18:00 WAT (excluding Nigerian public "
       "holidays). Critical incidents may be reported at any time and are worked continuously once acknowledged.")
d.row(["Severity", "Definition", "Response", "Restore target"], [80, 235, 95, 100], bold=True)
d.row(["Critical", "Platform or Customer tenant unavailable / data breach suspected", "4 business hrs", "24 hours"], [80, 235, 95, 100])
d.row(["High", "Core module or alerting materially degraded", "8 business hrs", "2 business days"], [80, 235, 95, 100])
d.row(["Medium", "Non-core function impaired; workaround exists", "2 business days", "5 business days"], [80, 235, 95, 100])
d.row(["Low", "Cosmetic issues, questions, enhancement requests", "5 business days", "scheduled release"], [80, 235, 95, 100])

d.section("4. SERVICE CREDITS")
d.para("If Monthly Platform Uptime falls below target, the Customer may claim a credit against the next invoice: "
       "below 99.5% → 5% of the monthly fee; below 99.0% → 10%; below 95.0% → 25%. Claims must be made within 30 "
       "days of the month concerned. Credits are the sole and exclusive remedy for availability shortfalls and are "
       "capped at 25% of the monthly fee.")

d.section("5. CUSTOMER RESPONSIBILITIES")
d.para("Keep credentials confidential and accounts limited to authorised personnel; use the service lawfully and "
       "within the licensed scope; provide accurate coordinates and records for field tools; report incidents "
       "promptly with reasonable detail.")

d.section("6. REVIEW")
d.para("On request, the Provider supplies a quarterly service report covering uptime, incidents and data-freshness "
       "statistics. This SLA is reviewed annually and may be updated by agreement of the parties.")

d.save()
print("built", OUT_SLA)

# ═════════════════ DPA ═════════════════
d = Doc(OUT_DPA, "EconomicBridge — Data Protection Addendum (DPA)",
        "Nigeria Data Protection Act 2023 · Schedule to the Master Services Agreement")

d.section("1. ROLES AND SCOPE")
d.para("For personal data processed in the course of the service, the Customer is the data controller and Bizra "
       "Farms Integrated Nigeria Limited (the Provider) is the data processor within the meaning of the Nigeria "
       "Data Protection Act 2023 (NDPA). This Addendum governs all such processing and prevails over conflicting "
       "terms of the master agreement in data-protection matters.")

d.section("2. WHAT PERSONAL DATA THE PLATFORM PROCESSES")
d.para("(a) Customer staff account data: names, work email addresses, roles and authentication records; "
       "(b) field records the Customer's officers choose to save: farm-owner names with farm coordinates and "
       "assessment results; (c) beneficiary telephone numbers supplied by the Customer or its partner agencies "
       "solely for SMS advisories. Satellite and Earth-observation data processed by the platform is not personal "
       "data. The Provider does not collect personal data from farmers directly; farmers require no registration.",
       bold_head="Categories.")
d.para("Providing, securing and supporting the service on the Customer's documented instructions — and for no "
       "other purpose. The Provider does not sell personal data, does not use it for advertising, and does not "
       "train models on it without separate written agreement.", bold_head="Purpose limitation.")

d.section("3. PROVIDER (PROCESSOR) OBLIGATIONS — NDPA 2023")
d.para("Process personal data only on the Customer's documented instructions; ensure persons authorised to process "
       "are bound by confidentiality; implement appropriate technical and organisational measures (Section 4); "
       "assist the Customer with data-subject rights requests and with its own NDPA obligations; notify the "
       "Customer without undue delay, and in any event within 72 hours, of becoming aware of a personal data "
       "breach affecting the Customer's data, with the information reasonably required for the Customer's own "
       "notifications; return or delete personal data at termination (Section 6); make available information "
       "reasonably necessary to demonstrate compliance, including an annual written attestation, and permit audits "
       "on 30 days' notice, at the Customer's cost, no more than once per year.")

d.section("4. SECURITY MEASURES (AS IMPLEMENTED)")
d.para("Tenant isolation by dedicated database schema per customer; encryption in transit (TLS/HTTPS throughout) "
       "and at rest (managed database encryption); role-based access control with least-privilege administrative "
       "access; audit logging of data-modifying operations; secrets held in a managed secrets store; infrastructure "
       "as code with reviewed, logged deployments; daily automated backups.")

d.section("5. HOSTING, TRANSFERS AND SUB-PROCESSORS")
d.para("The service is hosted on Amazon Web Services in the EU (Ireland, eu-west-1) region. To the extent this "
       "constitutes a cross-border transfer under Part VIII of the NDPA, the Provider relies on transfer to a "
       "jurisdiction with adequate data-protection law (the EU GDPR regime) together with the safeguards in this "
       "Addendum. The Provider will give 30 days' notice before any change of hosting region.",
       bold_head="5.1 Hosting.")
d.para("Amazon Web Services (cloud infrastructure, EU-Ireland); Resend Inc. (transactional email delivery); "
       "Mapbox Inc. (reverse geocoding of coordinates — no names attached); AWS SNS (SMS delivery to beneficiary "
       "numbers where SMS advisories are enabled). The Provider remains responsible for its sub-processors and "
       "will give 30 days' notice of additions or replacements, during which the Customer may object on "
       "reasonable data-protection grounds.", bold_head="5.2 Sub-processors.")

d.section("6. RETENTION AND DELETION")
d.para("Personal data is retained only for the duration of the service. Within 30 days of termination the "
       "Provider will, at the Customer's choice, return personal data in a standard machine-readable format or "
       "delete it, and will complete deletion from rolling backups within a further 90 days, confirming completion "
       "in writing.")

d.section("7. GENERAL")
d.para("Governing law: the laws of the Federal Republic of Nigeria, including the NDPA 2023 and regulations of "
       "the Nigeria Data Protection Commission. Liability follows the master agreement. If any provision of this "
       "Addendum conflicts with mandatory law, the mandatory law prevails and the remainder stays in force.")

d.section("SIGNATURES")
d.para("Executed as a schedule to the Master Services Agreement dated ____________.")
d.y -= 26
half = (X1 - X0 - 30) / 2
for i, (nm, org) in enumerate([
    ("Abdullahi Zuru Ibrahim — Director/CEO", "Bizra Farms Integrated Nigeria Limited"),
    ("Name/Title: ______________________", "Customer: ________________________"),
]):
    x = X0 + i * (half + 30)
    d.c.setStrokeColor(INK)
    d.c.setLineWidth(0.8)
    d.c.line(x, d.y, x + half, d.y)
    d.c.setFont(BODY_B, 8.6)
    d.c.setFillColor(INK)
    d.c.drawString(x, d.y - 12, nm)
    d.c.setFont(BODY, 8.2)
    d.c.setFillColor(MUTED)
    d.c.drawString(x, d.y - 23, org + "  ·  Signature & date")

d.save()
print("built", OUT_DPA)
