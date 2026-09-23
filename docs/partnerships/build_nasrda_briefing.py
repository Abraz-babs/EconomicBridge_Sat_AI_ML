"""Render the NASRDA DG briefing and meeting prep from their Markdown sources.

The Markdown files are the source of truth; these PDFs are generated from them,
so a correction is made once, in the .md, and re-rendered here. That rule exists
because the June versions of both PDFs carried claims our own later measurement
contradicted, and the script that built them was never kept.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nasrda_briefing.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, ListFlowable, ListItem, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

HERE = Path(__file__).parent
DOWNLOADS = Path(r"C:\Users\HP\Downloads")
LOGO = DOWNLOADS / "Company Logo.jpg"

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
BROWN = colors.HexColor("#6e2b2b")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef6f0")
RULE = colors.HexColor("#c9d6cd")

ss = getSampleStyleSheet()
SERIF, SERIF_B, SERIF_I = "Times-Roman", "Times-Bold", "Times-Italic"
title = ParagraphStyle("t", fontName=SERIF_B, fontSize=16, leading=20,
                       textColor=DGREEN, spaceAfter=4)
h2 = ParagraphStyle("h2", fontName=SERIF_B, fontSize=12.5, leading=16,
                    textColor=DGREEN, spaceBefore=10, spaceAfter=4,
                    keepWithNext=1)  # never strand a heading at a page foot
h3 = ParagraphStyle("h3", fontName=SERIF_B, fontSize=11, leading=14,
                    textColor=INK, spaceBefore=6, spaceAfter=2,
                    keepWithNext=1)
body = ParagraphStyle("b", fontName=SERIF, fontSize=10.5, leading=14.2,
                      textColor=INK, spaceAfter=5)
quote = ParagraphStyle("q", parent=body, fontName=SERIF_I, leftIndent=12,
                       textColor=GREY, borderPadding=(0, 0, 0, 6))
cell = ParagraphStyle("c", fontName=SERIF, fontSize=9, leading=11.5, textColor=INK)
cellh = ParagraphStyle("ch", parent=cell, fontName=SERIF_B, textColor=colors.white)
small = ParagraphStyle("s", fontName=SERIF, fontSize=8.5, leading=11,
                       textColor=GREY, alignment=1)


def inline(text: str) -> str:
    """Markdown emphasis and code to ReportLab markup, escaping the rest."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def table(rows: list[list[str]]) -> Table:
    head, *rest = rows
    data = [[Paragraph(inline(c), cellh) for c in head]]
    data += [[Paragraph(inline(c), cell) for c in r] for r in rest]
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DGREEN),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def render(md: str) -> list:
    story: list = [
        Image(str(LOGO), width=260, height=260 * 390 / 1024, hAlign="CENTER"),
        Spacer(1, 3),
        HRFlowable(width="100%", thickness=1.4, color=GREEN, spaceAfter=1),
        HRFlowable(width="100%", thickness=0.5, color=BROWN, spaceAfter=4),
        Paragraph("BIZRA FARMS INTEGRATED NIGERIA LIMITED (RC 1929412)",
                  ParagraphStyle("lh", parent=small, fontName=SERIF_B,
                                 textColor=DGREEN)),
        Spacer(1, 10),
    ]
    lines = md.splitlines()
    i, bullets, tbl = 0, [], []

    def flush():
        nonlocal bullets, tbl
        if bullets:
            story.append(ListFlowable(
                [ListItem(Paragraph(inline(b), body), leftIndent=12) for b in bullets],
                bulletType="bullet", start="•", leftIndent=10))
            bullets = []
        if tbl:
            story.append(KeepTogether([table(tbl), Spacer(1, 6)]))
            tbl = []

    while i < len(lines):
        raw = lines[i].rstrip()
        s = raw.strip()
        if s.startswith("|"):
            if bullets:
                flush()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                tbl.append(cells)
        elif s.startswith("- "):
            if tbl:
                flush()
            bullets.append(s[2:])
        else:
            flush()
            if not s:
                pass
            elif s == "---":
                story.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                                        spaceBefore=4, spaceAfter=6))
            elif s.startswith("# "):
                story.append(Paragraph(inline(s[2:]), title))
            elif s.startswith("## "):
                story.append(Paragraph(inline(s[3:]), h2))
            elif s.startswith("### "):
                story.append(Paragraph(inline(s[4:]), h3))
            elif s.startswith("> "):
                story.append(Paragraph(inline(s[2:]), quote))
            else:
                story.append(Paragraph(inline(s), body))
        i += 1
    flush()
    story = _bind_headings(story)
    story += [
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4),
        Paragraph("bizra@economicbridge.org &nbsp;·&nbsp; economicbridge.org "
                  "&nbsp;·&nbsp; +234 703 791 9465", small),
    ]
    return story


def _bind_headings(story: list) -> list:
    """Keep every section heading on the same page as the block beneath it.

    The keepWithNext style flag was not honoured next to a KeepTogether table,
    and left "3. The satellite base" stranded at the foot of page 1 with its
    table on page 2. Binding the pair explicitly is deterministic.
    """
    out, i = [], 0
    while i < len(story):
        f = story[i]
        is_head = isinstance(f, Paragraph) and f.style.name in ("h2", "h3")
        if is_head and i + 1 < len(story):
            out.append(KeepTogether([f, story[i + 1]]))
            i += 2
            continue
        out.append(f)
        i += 1
    return out


def build(src: str, out: str) -> Path:
    md = (HERE / src).read_text(encoding="utf-8")
    path = HERE / out
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=out.replace(".pdf", ""),
                            author="Bizra Farms Integrated Nigeria Limited")
    doc.build(render(md))
    shutil.copy2(path, DOWNLOADS / out)
    return path


if __name__ == "__main__":
    for src, out in (("EconomicBridge_DG_Briefing.md", "EconomicBridge_DG_Briefing.pdf"),
                     ("NASRDA_Meeting_Prep.md", "NASRDA_Meeting_Prep.pdf")):
        # The meeting prep is gitignored on purpose — it holds candid internal
        # notes and the repository is public — so it exists only on the
        # operator's machine. Skip it cleanly anywhere else.
        if not (HERE / src).exists():
            print(f"skipped {src} (local-only, not in the repository)")
            continue
        p = build(src, out)
        print(f"built {p.name}  ({p.stat().st_size // 1024} KB)  -> also copied to Downloads")
