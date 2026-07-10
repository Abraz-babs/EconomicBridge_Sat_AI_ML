"""EconomicBridge 'Road to A+' execution plan — multi-page PDF.

Codifies the honest product grading (composite B+, 2026-07-10) and the
concrete, sequenced work that moves every dimension to A+. Banked for
leadership consideration; revisit quarterly.

    apps/api/.venv/Scripts/python.exe docs/strategy/build_aplus_plan.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\HP\Downloads\EconomicBridge_Road_to_APlus.pdf")
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
c = canvas.Canvas(str(OUT), pagesize=A4)
X0, X1 = 42, W - 42


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


PAGE = [0]


def footer():
    c.setFillColor(MUTED)
    c.setFont(BODY, 7.6)
    c.drawCentredString((X0 + X1) / 2, 30,
                        "EconomicBridge · Bizra Farms Integrated Nigeria Ltd · Road to A+ · "
                        "10 July 2026 · confidential — internal execution plan")
    c.drawRightString(X1, 30, f"p. {PAGE[0]}")


def new_page(title, sub=None):
    if PAGE[0] > 0:
        footer()
        c.showPage()
    PAGE[0] += 1
    y = H - 48
    if PAGE[0] == 1 and LOGO.exists():
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(str(LOGO))
            iw, ih = ir.getSize()
            c.drawImage(ir, X0, y - 8, width=40, height=40 * ih / iw, mask="auto")
            c.setFillColor(DGREEN); c.setFont(BODY_B, 17)
            c.drawString(X0 + 48, y + 10, title)
            if sub:
                c.setFillColor(MUTED); c.setFont(BODY, 9.2)
                c.drawString(X0 + 48, y - 5, sub)
            return y - 34
        except Exception:  # noqa: BLE001
            pass
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 15)
    c.drawString(X0, y, title)
    if sub:
        c.setFillColor(MUTED); c.setFont(BODY, 9)
        c.drawString(X0, y - 14, sub)
        return y - 34
    return y - 22


def section(y, label, accent=GREEN):
    if y < 110:  # crude page-break guard
        y = new_page("Road to A+ (continued)")
    c.setFillColor(TINT)
    c.setStrokeColor(accent)
    c.setLineWidth(0.9)
    c.roundRect(X0, y - 18, X1 - X0, 21, 4, stroke=1, fill=1)
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 10.5)
    c.drawString(X0 + 8, y - 11.5, label)
    return y - 32


def para(y, text, size=9.4, leading=12.6, font=None, color=INK, indent=0, before=0):
    if y < 90:
        y = new_page("Road to A+ (continued)")
    f = font or BODY
    y -= before
    lines = wrap(text, f, size, X1 - X0 - indent)
    c.setFont(f, size)
    c.setFillColor(color)
    for ln in lines:
        c.drawString(X0 + indent, y, ln)
        y -= leading
    return y - 2


def simple_bullet(y, text, bold_head=None, size=9.3):
    if y < 90:
        y = new_page("Road to A+ (continued)")
    c.setFillColor(GREEN)
    c.setFont(BODY_B, size)
    c.drawString(X0 + 4, y, "—")
    hx = X0 + 18
    full = (bold_head + " " + text) if bold_head else text
    lines = wrap(full, BODY, size, X1 - hx - 2)
    for i, ln in enumerate(lines):
        if y < 80:
            y = new_page("Road to A+ (continued)")
        if i == 0 and bold_head:
            c.setFont(BODY_B, size); c.setFillColor(INK)
            c.drawString(hx, y, bold_head)
            off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
            c.setFont(BODY, size)
            c.drawString(hx + off, y, ln[len(bold_head):].lstrip())
        else:
            c.setFont(BODY, size); c.setFillColor(INK)
            c.drawString(hx, y, ln)
        y -= 12.4
    return y - 3


# ═════════ PAGE 1 — WHERE WE STAND + WHAT A+ MEANS ═════════
y = new_page("EconomicBridge — Road to A+",
             "Execution plan from the honest product grading of 10 July 2026 · revisit quarterly")

y = section(y, "1. WHERE WE STAND — THE HONEST GRADE")
y = para(y, "Composite grade: B+ (10 July 2026). Measured against our stage (pre-revenue, self-funded "
            "West African startup): A−. Measured against what we aspire to be (production, "
            "government-grade Earth-observation intelligence): B−. The platform is real, live at "
            "economicbridge.org, autonomous (daily satellite scan chain runs unattended), honestly "
            "labelled, patent-filed (NG/PT/NC/O/2026/23780), and funded for ~11 months of AWS runway. "
            "What separates B+ from A+ is not more features — it is PROOF: proven detections, a paying "
            "government customer, production-grade operations, and uniform depth across all 7 modules.")

y = section(y, "2. DEFINITION OF A+ — FOUR TESTS, ALL MUST PASS")
y = simple_bullet(y, "an independent party (state government or NASRDA) has confirmed our detections in the field, and we publish the measured accuracy.", "PROVEN:")
y = simple_bullet(y, "at least one signed government MOU converted to a paid invoice through the corporate account.", "PAID:")
y = simple_bullet(y, "externally measured uptime ≥ 99.5% over 90 days, a rehearsed disaster-recovery drill, and a security review on record.", "PRODUCTION:")
y = simple_bullet(y, "no weak tab — every module carries real data, real analytics, provenance, and an accuracy/coverage card a skeptical reviewer can check.", "UNIFORM:")

y = section(y, "3. SCOREBOARD — DIMENSION BY DIMENSION")
rows = [
    ("Data genuineness", "A−", "A+", "publish per-module provenance + coverage cards in-app"),
    ("Intelligence validation", "C+", "A+", "field ground-truth program + published precision/recall"),
    ("Engineering / architecture", "B+", "A", "multi-AZ verified, restore drill, load test"),
    ("Operations / reliability", "B−", "A", "external uptime monitor, alarms, status page, SLA"),
    ("Security / compliance", "B", "A", "secrets audit, pentest, NDPA documentation pack"),
    ("Module depth (weakest tab)", "B−", "A−", "Skills/Mobility/Aid analytics parity + Spotlight pattern"),
    ("ML honesty & performance", "B", "A", "locally-labelled retraining + per-class metrics card"),
    ("Commercial proof", "D", "A", "1 signed MOU → 1 paid pilot invoice"),
    ("Partnerships & moat", "A−", "A+", "NASRDA validation MOU + Esri program acceptance"),
]
col_x = [X0, X0 + 168, X0 + 205, X0 + 245]
c.setFont(BODY_B, 8.2); c.setFillColor(MUTED)
for cx, h in zip(col_x, ["DIMENSION", "NOW", "TARGET", "WHAT CLOSES THE GAP"]):
    c.drawString(cx, y, h)
y -= 13
for name, now, tgt, gap in rows:
    if y < 80:
        y = new_page("Road to A+ (continued)")
    c.setFont(BODY_B, 8.6); c.setFillColor(INK)
    c.drawString(col_x[0], y, name)
    c.setFont(BODY, 8.6); c.setFillColor(AMBER)
    c.drawString(col_x[1], y, now)
    c.setFillColor(GREEN)
    c.drawString(col_x[2], y, tgt)
    c.setFillColor(INK); c.setFont(BODY, 8.2)
    for i, ln in enumerate(wrap(gap, BODY, 8.2, X1 - col_x[3])):
        c.drawString(col_x[3], y - i * 10.5, ln)
        if i:
            y -= 10.5
    y -= 14

# ═════════ PAGE 2 — PILLAR 1 & 2 ═════════
y = new_page("Pillar 1 — Prove the intelligence  ·  Pillar 2 — Win a paying customer")

y = section(y, "PILLAR 1 — PROVE THE INTELLIGENCE (heaviest weight; C+ → A+)")
y = para(y, "Our detections are honest but unproven: no independent party has yet confirmed that a "
            "warning preceded a real event. One field-verified detection with a government's name on "
            "it is worth more than any feature.")
y = simple_bullet(y, "recruit state extension officers / NASRDA field staff to verify 20+ encroachment detections on the ground (start Kebbi + FCT — our densest feeds). Each verification logged: alert id, coordinate, field outcome (confirmed / partial / false). Target: first 5 verifications within 30 days of a partner saying yes.", "Ground-truth program:")
y = simple_bullet(y, "build a small verification ledger (admin panel) so outcomes accumulate into measured PRECISION per module — then publish the number in-app (\"27 of 34 field-checked alerts confirmed\"). Honesty is the brand; a real number beats a claimed one, even when modest.", "Accuracy ledger:")
y = simple_bullet(y, "backtest the conflict/encroachment detector against public incident data (e.g. ACLED events near our historical alerts, window-matched). Publishable without field visits; complements, never replaces, ground truth.", "Backtesting:")
y = simple_bullet(y, "collect locally-labelled Nigerian leaf photos through Farm Check partners (target 300–500/class for the top 4 crops) → fine-tune the ResNet-50 → publish per-class validation on LOCAL data. Kills the \"public dataset only\" critique.", "CropGuard local retraining:")
y = simple_bullet(y, "propose a joint validation MOU to NASRDA: they supply field checks + credibility, we supply the platform + data access. Converts the reviewer-critique dynamic into co-authorship.", "NASRDA validation MOU:")

y = section(y, "PILLAR 2 — WIN A PAYING CUSTOMER (D → A)")
y = simple_bullet(y, "complete corporate NGN current + USD domiciliary accounts (checklist pack ready) — the precondition for receiving any public money.", "Banking first:")
y = simple_bullet(y, "director-led Federal/State push using the commercial pack (USD tiers, revenue-share bands, PPP MOU template). Target: 1 signed state MOU within 90 days; convert to a paid pilot at the published tier — even a discounted first invoice counts as commercial proof.", "One state, one invoice:")
y = simple_bullet(y, "treat grant wins as commercial proof too: NSIA (shortlist due 31 Jul), WFP, Esri Startup. Any award or in-kind acceptance strengthens the A+ case and is already in motion.", "Grants channel:")
y = simple_bullet(y, "every demo ends with a concrete ask (MOU draft attached, pilot scope pre-written). We already have the assets; the discipline is the ask.", "Always be closing:")

# ═════════ PAGE 3 — PILLAR 3 & 4 ═════════
y = new_page("Pillar 3 — Production-grade operations  ·  Pillar 4 — Uniform module depth")

y = section(y, "PILLAR 3 — PRODUCTION-GRADE OPERATIONS (B− → A) — now affordable with Activate credits")
y = simple_bullet(y, "external uptime monitor on economicbridge.org + all 4 service health endpoints (free tier of any monitor); alarm to bizra@ + SMS. Start the 90-day 99.5% measurement clock immediately — A+ requires the measured window, so the clock must start now.", "Measure uptime externally:")
y = simple_bullet(y, "verify RDS backups by actually restoring one into a scratch instance and running the smoke suite against it; document the drill as a runbook (RPO/RTO stated). An untested backup is a hope, not a plan.", "Restore drill:")
y = simple_bullet(y, "re-enable Container Insights (~$20/mo, now funded), CloudWatch alarms on service health/5xx/CPU, and fix the known observability gap: the encroachment sweep must record to ingestion_runs like every other job.", "Alarms + observability:")
y = simple_bullet(y, "security pass: rotate all secrets into Secrets Manager (finish the stragglers), dependency audit (pip-audit / npm audit) in CI, then a low-cost penetration test; file the report — government due diligence asks for it.", "Security review:")
y = simple_bullet(y, "write the SLA we would sign (99.5%, support hours, incident response) + the NDPA-2023 compliance pack (data inventory, DPA template, retention policy). Selling to government without these stalls at procurement.", "Paper the promises:")

y = section(y, "PILLAR 4 — UNIFORM MODULE DEPTH (weakest tab B− → A−)")
y = simple_bullet(y, "bring Skills, Mobility and Aid to analytics parity: per-LGA drill-in, trend lines, provenance cards — the pattern Farmland/CropGuard already set. No new data needed; it is presentation depth.", "Depth parity:")
y = simple_bullet(y, "ship Alert Spotlight Phase 1 (approved 10 Jul: idle = state briefing, deterministic summaries composed only from alert-card values — no generative model). Extend the Spotlight pattern to ShockGuard next.", "Spotlight pattern:")
y = simple_bullet(y, "train the U-Net flood model when Phase-B raster labels exist; until then keep ShockGuard's honest statistical detectors and say so in-app (current wording already does).", "U-Net when ready:")
y = simple_bullet(y, "per-module accuracy/coverage cards (ties to Pillar 1): every tab answers \"how real is this?\" without the user asking.", "Trust cards:")

# ═════════ PAGE 4 — SEQUENCE, COSTS, RISKS ═════════
y = new_page("Sequence, costs, risks — the 90-day cut")

y = section(y, "90-DAY SEQUENCE (Jul 10 → Oct 10)")
y = para(y, "Month 1 (now → 10 Aug): start uptime clock + alarms + restore drill (Pillar 3 quick wins) · "
            "ship Spotlight P1 · open bank accounts · encroachment run-logging fix · NSIA shortlist "
            "response ready · propose NASRDA validation MOU.", before=2)
y = para(y, "Month 2 (→ 10 Sep): first 5–10 field verifications logged · accuracy ledger in admin · "
            "backtest study drafted · Skills/Mobility/Aid depth parity pass 1 · security audit + "
            "dependency scanning in CI · state MOU push with director.", before=4)
y = para(y, "Month 3 (→ 10 Oct): publish first accuracy cards in-app · pentest booked/done · "
            "90-day uptime window matures · CropGuard local-label collection running · target: "
            "MOU signed, first invoice issued.", before=4)

y = section(y, "COSTS (fits the $1,000 Activate envelope)")
y = para(y, "Almost everything above is time, not money. Cash items: Container Insights ~$20/mo · "
            "uptime monitor $0 (free tier) · pentest $0–500 (community/startup-rate) · field "
            "verification travel — partner-borne under the NASRDA/state MOU model · AWS steady-state "
            "~$90/mo already covered by credits.", before=2)

y = section(y, "TOP RISKS & MITIGATIONS")
y = simple_bullet(y, "government partners move slowly → run NASRDA MOU, state MOU and grants in parallel; any ONE landing satisfies the proof pillar first.", "Partner latency:")
y = simple_bullet(y, "field verifications may return false positives → that is still a WIN: a measured precision number plus detector tuning beats an unmeasured claim; publish honestly either way.", "Truth risk:")
y = simple_bullet(y, "solo-execution bandwidth → this plan is deliberately sequenced so Pillar 3 (mostly one-time setup) front-loads while Pillars 1–2 wait on external replies; nothing blocks on everything.", "Bandwidth:")
y = simple_bullet(y, "scope temptation → new modules/features are frozen below Spotlight P1/P2 priority until the four A+ tests pass. Depth beats breadth from here.", "Focus:")

y = section(y, "THE ONE-SENTENCE VERSION")
y = para(y, "A+ = one confirmed detection, one paid invoice, one measured 99.5% quarter, and no weak "
            "tab — everything in this plan exists to produce those four artifacts.", font=BODY_B, size=10.2)

footer()
c.showPage()
c.save()
print("built", OUT)
