"""Render a Markdown doc to a branded PDF (headings, bullets, tables, code,
bold/italic). Lightweight - handles the subset our docs use, no pandoc needed.

    apps/api/.venv/Scripts/python.exe docs/md_to_pdf.py <input.md> [output.pdf]
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
BROWN = colors.HexColor("#6e2b2b")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef6f0")

ss = getSampleStyleSheet()
S = {
    "h1": ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=DGREEN,
                         spaceBefore=6, spaceAfter=8, alignment=0),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=14, textColor=DGREEN,
                         spaceBefore=12, spaceAfter=4),
    "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11.5,
                         textColor=BROWN, spaceBefore=8, spaceAfter=2),
    "body": ParagraphStyle("body", parent=ss["Normal"], fontSize=9.7, leading=13.5,
                           textColor=INK, spaceAfter=5),
    "bullet": ParagraphStyle("bullet", parent=ss["Normal"], fontSize=9.7,
                             leading=13.5, textColor=INK, leftIndent=14,
                             bulletIndent=4, spaceAfter=2),
    "cell": ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, leading=11,
                           textColor=INK),
    "cellh": ParagraphStyle("cellh", parent=ss["Normal"], fontSize=8.5, leading=11,
                            textColor=colors.white, fontName="Helvetica-Bold"),
    "code": ParagraphStyle("code", parent=ss["Code"], fontSize=8, leading=10,
                           textColor=INK, backColor=LIGHT, borderPadding=6),
}


def inline(text: str) -> str:
    """Markdown inline -> reportlab mini-HTML."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)  # links -> just the text
    return text


def render(md_path: Path, out_path: Path) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    flow: list = []
    buf: list[str] = []
    kind = {"v": None}  # 'p' (paragraph) or 'li' (list item)

    def flush():
        if not buf:
            return
        txt = inline(" ".join(buf))
        if kind["v"] == "li":
            flow.append(Paragraph(txt, S["bullet"], bulletText="•"))
        else:
            flow.append(Paragraph(txt, S["body"]))
        buf.clear()
        kind["v"] = None

    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()

        if stripped.startswith("```"):              # code fence
            flush()
            i += 1
            cbuf = []
            while i < n and not lines[i].strip().startswith("```"):
                cbuf.append(lines[i])
                i += 1
            flow.append(Preformatted("\n".join(cbuf), S["code"]))
            flow.append(Spacer(1, 4))
        elif stripped.startswith("# "):
            flush()
            flow.append(Paragraph(inline(stripped[2:]), S["h1"]))
            flow.append(HRFlowable(width="100%", thickness=1.2, color=GREEN,
                                   spaceBefore=2, spaceAfter=6))
        elif stripped.startswith("## "):
            flush()
            flow.append(Paragraph(inline(stripped[3:]), S["h2"]))
        elif stripped.startswith("### "):
            flush()
            flow.append(Paragraph(inline(stripped[4:]), S["h3"]))
        elif stripped == "---":
            flush()
            flow.append(HRFlowable(width="100%", thickness=0.5, color=BROWN,
                                   spaceBefore=4, spaceAfter=4))
        elif stripped.startswith("|") and stripped.endswith("|"):
            flush()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            i -= 1
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            if rows:
                header, *bodyrows = rows
                data = [[Paragraph(inline(c), S["cellh"]) for c in header]] + \
                       [[Paragraph(inline(c), S["cell"]) for c in r] for r in bodyrows]
                ncols = len(header)
                tbl = Table(data, colWidths=[(176 / ncols) * mm] * ncols)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), GREEN),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                flow.append(tbl)
                flow.append(Spacer(1, 6))
        elif stripped.startswith(("- ", "* ", "• ")):
            flush()                                  # start a new list item
            kind["v"] = "li"
            buf.append(stripped[2:])
        elif stripped == "":
            flush()
        else:                                        # continuation of para / li
            if kind["v"] is None:
                kind["v"] = "p"
            buf.append(stripped)
        i += 1
    flush()

    SimpleDocTemplate(
        str(out_path), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm, title=md_path.stem,
    ).build(flow)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    render(src, dst)
    print(f"wrote {dst} ({dst.stat().st_size} bytes)")
