"""Generate the commercial partnership pack PDFs from their markdown sources:
Pricing Sheet, Revenue-Share Framework, and PPP MOU Template. Branded, A4.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_commercial_pack.py
"""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

HERE = Path(__file__).parent
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

# Helvetica lacks the naira glyph (U+20A6); register a Windows font that has
# it and use it as the body face. Falls back to Helvetica + "NGN" text.
BODY, BODY_B, BODY_I = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
try:
    pdfmetrics.registerFont(TTFont("EBBody", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyB", r"C:\Windows\Fonts\arialbd.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyI", r"C:\Windows\Fonts\ariali.ttf"))
    pdfmetrics.registerFont(TTFont("EBBodyBI", r"C:\Windows\Fonts\arialbi.ttf"))
    pdfmetrics.registerFontFamily(
        "EBBody", normal="EBBody", bold="EBBodyB",
        italic="EBBodyI", boldItalic="EBBodyBI",
    )
    BODY, BODY_B, BODY_I = "EBBody", "EBBodyB", "EBBodyI"
except Exception:  # noqa: BLE001
    pass
_HAS_NAIRA = BODY == "EBBody"

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
ROW_ALT = colors.HexColor("#f0f7f2")

DOCS = [
    ("EconomicBridge_Pricing_Sheet.md", "EconomicBridge_Pricing_Sheet.pdf"),
    ("EconomicBridge_Revenue_Share_Framework.md", "EconomicBridge_Revenue_Share_Framework.pdf"),
    ("EconomicBridge_PPP_MOU_Template.md", "EconomicBridge_PPP_MOU_Template.pdf"),
]


def _style(name: str, **kw) -> ParagraphStyle:
    base = dict(fontName=BODY, fontSize=9.2, leading=13, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S_H1 = _style("h1", fontName=BODY_B, fontSize=15, leading=19, textColor=DGREEN, spaceAfter=2)
S_H2 = _style("h2", fontName=BODY_B, fontSize=11.5, leading=15, textColor=DGREEN, spaceBefore=8, spaceAfter=3)
S_H3 = _style("h3", fontName=BODY_B, fontSize=10, leading=13, textColor=GREEN, spaceBefore=6, spaceAfter=2)
S_P = _style("p", alignment=TA_JUSTIFY, spaceAfter=4)
S_META = _style("meta", fontSize=8.4, leading=11.5, textColor=MUTED, spaceAfter=4)
S_LI = _style("li", leftIndent=10, spaceAfter=2.5)
S_CELL = _style("cell", fontSize=8.4, leading=11)
S_CELL_H = _style("cellh", fontName=BODY_B, fontSize=8.4, leading=11, textColor=colors.white)


def _inline(text: str) -> str:
    """Markdown inline -> reportlab mini-HTML."""
    if not _HAS_NAIRA:
        text = text.replace("₦", "NGN ")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("&amp;nbsp;", "&nbsp;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def _table(rows: list[list[str]]) -> Table:
    data = [[Paragraph(_inline(c), S_CELL_H if i == 0 else S_CELL) for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, hAlign="LEFT", colWidths=None, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DGREEN),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d8cd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for r in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def render(md_path: Path, pdf_path: Path) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    story: list = []

    if LOGO.exists():
        img = Image(str(LOGO))
        img.drawHeight = 14 * mm * img.drawHeight / img.drawWidth
        img.drawWidth = 14 * mm
        img.hAlign = "LEFT"
        story += [img, Spacer(1, 3)]

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not set("".join(cells)) <= set("-: "):
                    rows.append(cells)
                i += 1
            story += [Spacer(1, 2), _table(rows), Spacer(1, 4)]
            continue
        if line.startswith("### "):
            story.append(Paragraph(_inline(line[4:]), S_H3))
        elif line.startswith("## "):
            story.append(Paragraph(_inline(line[3:]), S_H2))
        elif line.startswith("# "):
            story.append(Paragraph(_inline(line[2:]), S_H1))
        elif line == "---":
            story.append(HRFlowable(width="100%", thickness=0.6, color=GREEN,
                                    spaceBefore=5, spaceAfter=5))
        elif line.startswith("- "):
            story.append(Paragraph("•&nbsp;&nbsp;" + _inline(line[2:]), S_LI))
        elif re.match(r"^\d+\.\d*\s|^\d+\.\s", line):
            story.append(Paragraph(_inline(line), S_P))
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            story.append(Paragraph(_inline(line.strip("*")), S_META))
        else:
            story.append(Paragraph(_inline(line), S_P))
        i += 1

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm,
        title=pdf_path.stem.replace("_", " "),
        author="Bizra Farms Integrated Nigeria Ltd",
    )
    doc.build(story)
    print(f"  built {pdf_path.name}")


if __name__ == "__main__":
    for src, dst in DOCS:
        render(HERE / src, HERE / dst)
    print("done")
