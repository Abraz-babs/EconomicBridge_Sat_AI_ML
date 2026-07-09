"""One-trip bank-visit pack for opening Bizra Farms' corporate accounts:
page 1 = document checklist (NGN current + USD domiciliary), page 2 = a
ready-to-adapt board resolution template banks require.

    apps/api/.venv/Scripts/python.exe docs/company/build_bank_checklist.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\HP\Downloads\Bizra_Bank_Account_Checklist.pdf")
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
X0, X1 = 40, W - 40


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


def header(title, sub):
    y = H - 46
    if LOGO.exists():
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(str(LOGO))
            iw, ih = ir.getSize()
            c.drawImage(ir, X0, y - 8, width=38, height=38 * ih / iw, mask="auto")
        except Exception:  # noqa: BLE001
            pass
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 15.5)
    c.drawString(X0 + 46, y + 10, title)
    c.setFillColor(MUTED)
    c.setFont(BODY, 9)
    c.drawString(X0 + 46, y - 4, sub)
    return y - 30


def section(y, label):
    c.setFillColor(TINT)
    c.setStrokeColor(GREEN)
    c.setLineWidth(0.8)
    c.roundRect(X0, y - 18, X1 - X0, 20, 4, stroke=1, fill=1)
    c.setFillColor(DGREEN)
    c.setFont(BODY_B, 10.5)
    c.drawString(X0 + 8, y - 12, label)
    return y - 30


def item(y, text, bold_prefix=None, indent=0):
    """A checkbox line; wraps. Returns new y."""
    bx = X0 + 4 + indent
    c.setStrokeColor(INK)
    c.setLineWidth(0.9)
    c.rect(bx, y - 1.5, 8, 8, stroke=1, fill=0)
    tx = bx + 14
    maxw = X1 - tx - 4
    if bold_prefix:
        full = bold_prefix + " " + text
    else:
        full = text
    lines = wrap(full, BODY, 9.3, maxw)
    for i, ln in enumerate(lines):
        if i == 0 and bold_prefix and ln.startswith(bold_prefix):
            c.setFont(BODY_B, 9.3)
            c.setFillColor(INK)
            c.drawString(tx, y, bold_prefix)
            off = pdfmetrics.stringWidth(bold_prefix + " ", BODY_B, 9.3)
            c.setFont(BODY, 9.3)
            c.drawString(tx + off, y, ln[len(bold_prefix):].lstrip())
        else:
            c.setFont(BODY, 9.3)
            c.setFillColor(INK)
            c.drawString(tx, y, ln)
        y -= 12
    return y - 3


def note(y, text):
    lines = wrap(text, BODY, 8.6, X1 - X0 - 12)
    c.setFillColor(MUTED)
    c.setFont(BODY, 8.6)
    for ln in lines:
        c.drawString(X0 + 6, y, ln)
        y -= 11
    return y - 3


# ══ PAGE 1 — CHECKLIST ══════════════════════════════════════════════════════
y = header("Corporate Account Opening — One-Trip Checklist",
           "Bizra Farms Integrated Nigeria Limited (RC 1929412) · NGN current account + USD domiciliary account")

y = section(y, "A. DOCUMENTS TO CARRY  (originals + 2 photocopies of each)")
y = item(y, "— Certificate of Incorporation (RC 1929412).", "CAC Certificate")
y = item(y, "(post-2020 CAC document showing directors, shareholders and share capital; replaces the old CO2/CO7). "
            "Print a fresh one from the CAC portal if older than ~6 months.", "CAC Status Report")
y = item(y, "— certified Memorandum & Articles of Association.", "MEMART")
y = item(y, "(company Tax Identification Number certificate / FIRS TIN printout).", "Company TIN")
y = item(y, "of BOTH signatories (Abdullahi Zuru Ibrahim + Zakiya Zuhair): BVN, NIN, and one valid photo ID each "
            "(international passport, NIN slip, or driver's licence).", "BVN + NIN + valid ID")
y = item(y, "on company letterhead naming the account signatories and signing mandate — ready-to-sign template on page 2.",
         "Board resolution")
y = item(y, "for the registered address (utility bill not older than 3 months).", "Proof of address")
y = item(y, "— 2 recent passport photographs per signatory.", "Passport photos")
y = item(y, "— two existing current-account holders (individuals or companies) each complete the bank's reference form. "
            "Collect the forms FIRST, get them signed, return. This is the usual delay — start it before the visit.",
         "Two current-account references")
y = item(y, "(if the company has one; some banks request it for mandates).", "Company seal / stamp")
y = note(y, "SCUML: as a private limited trading company, Bizra is generally outside SCUML scope, but if the bank "
            "insists (they sometimes do for agriculture/consulting), registration is free on the EFCC-SCUML portal.")

y = section(y, "B. AT THE BANK — ASK FOR BOTH ACCOUNTS IN ONE PROCESS")
y = item(y, "in the EXACT name “Bizra Farms Integrated Nigeria Limited” — grant and government payers "
            "match the beneficiary name to the legal entity letter-for-letter.", "Open the NGN current account")
y = item(y, "at the same sitting (same documents). Confirm it can RECEIVE international SWIFT wires, not just hold cash.",
         "Open the USD domiciliary account")
y = item(y, "— account name, account number, SWIFT/BIC code, bank branch address, and any correspondent-bank details. "
            "Every grant disbursement form asks for exactly these fields.", "Request a bank letter of account details")
y = item(y, "(inward wire charge, USD cash withdrawal rules, monthly maintenance).", "Ask the charges on inward SWIFT receipts")
y = item(y, "— decide the mandate BEFORE the visit: sole signatory (fast) or both-to-sign (stronger governance; "
            "investors prefer it for amounts above a threshold, e.g. either-to-sign below ₦5m, both above).",
         "Signing mandate")
y = item(y, "for the corporate profile (token/OTP for both directors).", "Set up corporate internet banking")

y = section(y, "C. AFTER OPENING")
y = item(y, "into the grant/application records: NSIA, WFP, and any government MOU will request them.",
         "File the account details letter")
y = item(y, "(Payoneer or Raenest business) as the fast lane for smaller international receipts — supplement, "
            "never the substitute for the domiciliary account.", "Add a fintech USD receiving account")
y = item(y, "— every prize, grant or contract payment goes to the COMPANY accounts, never personal. Clean books = "
            "clean NSIA equity due diligence.", "Discipline rule")

c.setFillColor(MUTED)
c.setFont(BODY, 8)
c.drawCentredString((X0 + X1) / 2, 42,
                    "Typical timeline: current account 3–10 working days once references are in · domiciliary a few days after. "
                    "Prepared 09 July 2026.")
c.showPage()

# ══ PAGE 2 — BOARD RESOLUTION TEMPLATE ══════════════════════════════════════
y = header("Board Resolution — Template (retype on company letterhead)",
           "Extract of resolution for opening corporate bank accounts · adapt bracketed items, then both directors sign")

c.setFillColor(INK)
para_w = X1 - X0
y -= 6

def para(y, text, size=9.8, leading=14, font=None, before=6):
    f = font or BODY
    lines = wrap(text, f, size, para_w)
    y -= before
    c.setFont(f, size)
    c.setFillColor(INK)
    for ln in lines:
        c.drawString(X0, y, ln)
        y -= leading
    return y

y = para(y, "BIZRA FARMS INTEGRATED NIGERIA LIMITED (RC 1929412)", font=BODY_B, size=11)
y = para(y, "EXTRACT OF THE RESOLUTION OF THE BOARD OF DIRECTORS PASSED AT THE MEETING HELD ON "
            "[DATE] AT [ADDRESS OF MEETING]", font=BODY_B, size=9.8)
y = para(y, "IT WAS RESOLVED AS FOLLOWS:", before=10)
y = para(y, "1.  That the Company opens a Naira (NGN) current account and a United States Dollar (USD) "
            "domiciliary account with [BANK NAME] (“the Bank”).", before=8)
y = para(y, "2.  That the following Directors of the Company are authorised as signatories to the said accounts:", before=8)
y = para(y, "      (a)  Abdullahi Zuru Ibrahim — Director / Chief Executive Officer", before=4)
y = para(y, "      (b)  Zakiya Zuhair — Director / Chief Financial Officer", before=4)
y = para(y, "3.  That the signing mandate on the accounts shall be: [EITHER SIGNATORY TO SIGN ALONE] / "
            "[BOTH SIGNATORIES TO SIGN JOINTLY] / [EITHER ALONE UP TO ₦[AMOUNT]; JOINTLY ABOVE THAT AMOUNT] "
            "(delete as applicable).", before=8)
y = para(y, "4.  That the Bank is authorised to honour all cheques, instructions and electronic mandates issued in "
            "accordance with the mandate above, and to accept inward local and international transfers "
            "(including SWIFT) for credit of the accounts.", before=8)
y = para(y, "5.  That the Directors named above are authorised to execute the Bank’s account-opening "
            "documentation, corporate internet-banking setup and any related forms on behalf of the Company.", before=8)
y = para(y, "Dated this ______ day of ____________ 2026.", before=16)

y -= 34
half = (X1 - X0 - 30) / 2
for i, (nm, role) in enumerate([
    ("Abdullahi Zuru Ibrahim", "Director / CEO"),
    ("Zakiya Zuhair", "Director / CFO"),
]):
    x = X0 + i * (half + 30)
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.line(x, y, x + half, y)
    c.setFont(BODY_B, 9.5)
    c.drawString(x, y - 13, nm)
    c.setFont(BODY, 9)
    c.setFillColor(MUTED)
    c.drawString(x, y - 25, role + "  ·  Signature & date")
    c.setFillColor(INK)

c.setFillColor(MUTED)
c.setFont(BODY, 8)
c.drawCentredString((X0 + X1) / 2, 42,
                    "Template only — retype on Bizra Farms letterhead; some banks supply their own resolution format, "
                    "in which case sign theirs and keep this as the fallback.")
c.showPage()
c.save()
print("built", OUT)
