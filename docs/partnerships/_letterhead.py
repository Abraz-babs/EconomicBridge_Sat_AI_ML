"""The company letterhead, shared by every document handed to a partner.

The directors set the standard on 24 July 2026 for any official engagement:
centred logo, a dark-green rule, the registered name and RC number beneath it,
and a two-line footer carrying the company email, phone, website and motto.
Builders use this module instead of drawing their own, so the NASRDA handouts
cannot drift apart again the way the June set did (a personal Gmail address in
one, a raw load-balancer hostname in another).

    story = letterhead() + [...]
    doc = SimpleDocTemplate(..., bottomMargin=BOTTOM_MARGIN)
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import HRFlowable, Image, Paragraph, Spacer

LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

DGREEN = colors.HexColor("#136b3a")
INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#5b6b60")
HAIRLINE = colors.HexColor("#c9d3cd")

SERIF, SERIF_B, SERIF_I = "Times-Roman", "Times-Bold", "Times-Italic"

FOOTER_LINES = (
    "Bizra Farms Integrated Nigeria Limited  \u2022  RC 1929412  \u2022  "
    "Kebbi State, Nigeria",
    "bizra@economicbridge.org  \u2022  +234 703 791 9465  \u2022  "
    "economicbridge.org  \u2022  Planting the seeds of Tomorrow",
)

# The footer is drawn at fixed heights (hairline at 58 pt); page templates
# leave this much room at the bottom so body text never runs into it.
BOTTOM_MARGIN = 72

_NAME = ParagraphStyle("lh_name", fontName=SERIF_B, fontSize=13.5, leading=16.5,
                       textColor=DGREEN, alignment=1)
_RC = ParagraphStyle("lh_rc", fontName=SERIF, fontSize=10.5, leading=13.5,
                     textColor=INK, alignment=1)


def letterhead(logo_width: float = 150) -> list:
    """Flowables for the top of the first page."""
    iw, ih = ImageReader(str(LOGO)).getSize()
    return [
        Image(str(LOGO), width=logo_width, height=logo_width * ih / iw,
              hAlign="CENTER"),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1.6, color=DGREEN, spaceAfter=9),
        Paragraph("BIZRA FARMS INTEGRATED NIGERIA LIMITED", _NAME),
        Paragraph("(RC 1929412)", _RC),
    ]


def draw_footer(canvas, doc) -> None:
    """Page callback: the two-line footer above a hairline, on every page."""
    x0, x1 = doc.leftMargin, doc.pagesize[0] - doc.rightMargin
    mid = (x0 + x1) / 2
    canvas.saveState()
    canvas.setStrokeColor(HAIRLINE)
    canvas.setLineWidth(0.7)
    canvas.line(x0, 58, x1, 58)
    canvas.setFillColor(MUTED)
    canvas.setFont(SERIF, 8.4)
    canvas.drawCentredString(mid, 47, FOOTER_LINES[0])
    canvas.drawCentredString(mid, 37, FOOTER_LINES[1])
    canvas.restoreState()
