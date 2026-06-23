"""Generate the NASRDA meeting kit: a one-page executive leave-behind and a
one-page live-demo script. Both branded, portrait A4, print-ready.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_meeting_kit.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402

HERE = Path(__file__).parent
DOWNLOADS = Path(r"C:\Users\HP\Downloads")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

# Register a glyph font that has check/cross/half symbols (Helvetica lacks
# them). Falls back to plain text marks if no candidate font is present.
SYMBOL_FONT = "Helvetica"
for _cand in (r"C:\Windows\Fonts\seguisym.ttf", r"C:\Windows\Fonts\arial.ttf"):
    try:
        pdfmetrics.registerFont(TTFont("EBSym", _cand))
        SYMBOL_FONT = "EBSym"
        break
    except Exception:  # noqa: BLE001
        pass
_HAS_SYM = SYMBOL_FONT != "Helvetica"

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
BROWN = colors.HexColor("#6e2b2b")
GOLD = colors.HexColor("#e8a81a")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef6f0")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13,
                      textColor=INK, alignment=TA_JUSTIFY, spaceAfter=5)
lead = ParagraphStyle("lead", parent=ss["Normal"], fontSize=11, leading=15,
                      textColor=INK, spaceAfter=8)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5, textColor=DGREEN,
                    spaceBefore=8, spaceAfter=3)
small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=11,
                       textColor=GREY)
bignum = ParagraphStyle("bignum", parent=ss["Normal"], fontSize=20,
                        textColor=GREEN, fontName="Helvetica-Bold", alignment=1)
numlbl = ParagraphStyle("numlbl", parent=ss["Normal"], fontSize=7.5, leading=9,
                        textColor=INK, alignment=1)
step = ParagraphStyle("step", parent=body, alignment=0, spaceAfter=7)


def header(story):
    story += [
        Image(str(LOGO), width=300, height=300 * 390 / 1024, hAlign="CENTER"),
        Spacer(1, 3),
        HRFlowable(width="100%", thickness=1.4, color=GREEN, spaceAfter=1),
        HRFlowable(width="100%", thickness=0.5, color=BROWN, spaceAfter=8),
    ]


# EO competitor comparison. Honest: ✓ full · ◑ partial · ✗ none. Columns:
# EconomicBridge, Planet/Maxar, EOS/Farmonaut, Digital Earth Africa.
_CAPS = [
    ("AI crop-disease diagnosis (from a leaf photo)", "ynnn"),
    ("Satellite crop / vegetation monitoring (NDVI)", "yyyy"),
    ("Flood & drought early warning", "yyny"),
    ("Farmer-herder conflict & encroachment warning", "ynnn"),
    ("Poverty & population mapping", "ypnp"),
    ("Aid-coordination & multi-agency coverage", "ynnn"),
    ("Unified multi-domain platform (ag + disaster + economy)", "ynnp"),
    ("Last-mile SMS alerts to farmers, local languages", "ynnn"),
    ("Honest live-vs-modelled data labelling", "ynnn"),
    ("Built for West-African governments (multi-tenant)", "yppp"),
    ("Owns a satellite constellation (imagery source)", "nynn"),
]
_SYM = {"y": ("✓", "#1f8a3b"), "p": ("◑", "#e8a81a"),
        "n": ("✗", "#c0c0c0")}


def _mark(kind: str):
    glyph, hexc = _SYM[kind]
    if not _HAS_SYM:                      # ASCII fallback
        glyph = {"y": "Yes", "p": "~", "n": "-"}[kind]
    cell = ParagraphStyle("mk", parent=ss["Normal"], alignment=1, fontSize=8)
    return Paragraph(
        f'<font name="{SYMBOL_FONT}" size="11" color="{hexc}">{glyph}</font>', cell)


def _legend() -> str:
    if not _HAS_SYM:
        return "Yes = full, ~ = partial, - = none."
    g, a, r = _SYM["y"][0], _SYM["p"][0], _SYM["n"][0]
    return (f'<font name="{SYMBOL_FONT}" color="#1f8a3b">{g}</font> full &nbsp; '
            f'<font name="{SYMBOL_FONT}" color="#e8a81a">{a}</font> partial &nbsp; '
            f'<font name="{SYMBOL_FONT}" color="#999999">{r}</font> none.')


def _comparison_table() -> Table:
    capc = ParagraphStyle("capc", parent=ss["Normal"], fontSize=8.3, leading=10,
                          textColor=INK)
    hdr = ParagraphStyle("hdrc", parent=ss["Normal"], fontSize=7.4, leading=8.6,
                         textColor=colors.white, fontName="Helvetica-Bold",
                         alignment=1)
    header = [
        Paragraph("Capability", ParagraphStyle("h0", parent=hdr, alignment=0)),
        Paragraph("Economic<br/>Bridge", hdr), Paragraph("Planet /<br/>Maxar", hdr),
        Paragraph("EOS /<br/>Farmonaut", hdr), Paragraph("Digital Earth<br/>Africa", hdr),
    ]
    data = [header] + [
        [Paragraph(cap, capc)] + [_mark(m) for m in marks] for cap, marks in _CAPS
    ]
    t = Table(data, colWidths=[70 * mm, 26 * mm, 26 * mm, 26 * mm, 26 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("BACKGROUND", (1, 1), (1, -1), LIGHT),          # highlight EB column
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
    ]))
    return t


def footer_line():
    return Paragraph(
        "Live: economicbridge-staging-alb-691775567.eu-west-1.elb.amazonaws.com "
        "&nbsp;|&nbsp; bizrafarms@gmail.com &nbsp;|&nbsp; +234 703 791 9465 "
        "&nbsp;|&nbsp; Bizra Farms Integrated Nigeria Limited", small)


# ─── 1. One-page executive leave-behind ───────────────────────────────────
def build_one_pager():
    out = HERE / "Bizra_NASRDA_OnePager.pdf"
    story = []
    header(story)
    story += [
        Paragraph("<b>EconomicBridge — Executive Brief</b>", h2),
        Paragraph(
            "A live satellite and AI platform that turns Earth observation into "
            "real impact for agriculture, food security and disaster response. "
            "Built and operated in Nigeria by Bizra Farms Integrated.", lead),
    ]
    stats = [
        [Paragraph("700+", bignum), Paragraph("10", bignum),
         Paragraph("87.2%", bignum), Paragraph("7", bignum)],
        [Paragraph("LGAs / districts covered", numlbl),
         Paragraph("pilot regions live", numlbl),
         Paragraph("AI crop-model accuracy", numlbl),
         Paragraph("live data feeds", numlbl)],
    ]
    t = Table(stats, colWidths=[42 * mm] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.white),
    ]))
    story += [t, Spacer(1, 8)]

    story += [
        Paragraph("What it does", h2),
        Paragraph(
            "<b>CropGuard</b> — AI crop-disease diagnosis from a leaf photo, plus "
            "satellite vegetation monitoring. &nbsp; <b>ShockGuard</b> — flood and "
            "drought detection from all-weather radar. &nbsp; <b>Farmland "
            "Protection</b> — herder/cattle encroachment & conflict early warning, "
            "fusing Sentinel-2 vegetation loss, Sentinel-1 radar disturbance and "
            "fire. &nbsp; <b>Economic Visibility</b> — poverty and "
            "population mapping from space. &nbsp; Plus mobility, education and "
            "aid-coordination intelligence. Warnings reach communities by SMS in "
            "local languages, no smartphone needed.", body),

        Paragraph("Built on", h2),
        Paragraph(
            "Live data from Copernicus Sentinel-1 and Sentinel-2, NASA, the World "
            "Bank, UNICEF and WorldPop; a trained ResNet-50 model plus conflict "
            "and anomaly prediction; running on AWS with multi-tenant data "
            "isolation and honest live-vs-modelled labelling.", body),

        Paragraph("Proposed collaboration with NASRDA", h2),
        Paragraph(
            "&bull; Integrate <b>NigeriaSat</b> imagery and the National Centre "
            "for Remote Sensing into the platform's intelligence.<br/>"
            "&bull; A flagship <b>joint demonstration</b> of applied Earth "
            "observation for food security and disaster resilience.<br/>"
            "&bull; A live <b>reference platform</b> for NASRDA's application "
            "centres.<br/>"
            "&bull; A path to a <b>data-sharing memorandum of understanding</b>.",
            body),
        Spacer(1, 5),
        Paragraph("How EconomicBridge compares in the EO landscape", h2),
        _comparison_table(),
        Spacer(1, 2),
        Paragraph(
            f"{_legend()} EconomicBridge competes on the applied-intelligence "
            "and last-mile layer over open Copernicus/NASA data. It does not "
            "own satellites — NASRDA's satellites and NCRS archives are its "
            "natural complement, not a competitor.", small),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.5, color=BROWN, spaceAfter=4),
        footer_line(),
    ]
    SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=9 * mm, bottomMargin=9 * mm,
        title="EconomicBridge - Executive Brief (NASRDA)",
    ).build(story)
    shutil.copy(out, DOWNLOADS / out.name)
    return out


# ─── 2. One-page live-demo script ─────────────────────────────────────────
def build_demo_script():
    out = HERE / "EconomicBridge_Demo_Script.pdf"
    story = []
    header(story)
    story += [
        Paragraph("<b>Live Demo Script &mdash; NASRDA Meeting</b>", h2),
        Paragraph(
            "Aim: walk out with a committed next step (technical session / path "
            "to a data-sharing MOU). Let the live product do the talking; keep "
            "it to ~6 minutes, then listen.", body),

        Paragraph("Pre-flight (before you walk in)", h2),
        Paragraph(
            "&bull; Phone hotspot ON and tested on the live URL (do not trust "
            "venue wifi).<br/>"
            "&bull; Browser full-screen (F11), logged in as super-admin, "
            "Overview + CropGuard tabs pre-loaded.<br/>"
            "&bull; Diseased-leaf photo on the laptop, pre-tested so it reads as "
            "a disease.<br/>"
            "&bull; Pitch deck PDF + demo video saved offline as a fallback.", body),

        Paragraph("The walkthrough", h2),
        Paragraph("<b>1. Front door.</b> SHOW the public site. SAY: \"This is "
                  "EconomicBridge, live and open. Now the operational view.\"", step),
        Paragraph("<b>2. Overview.</b> SHOW the map, pulsing halos, rotating "
                  "intel. SAY: \"447 LGAs, 10 regions, updating from satellites "
                  "every day.\"", step),
        Paragraph("<b>3. CropGuard upload &mdash; THE MOMENT.</b> Upload the leaf. "
                  "SHOW the diagnosis + the heatmap of where the AI looked. SAY: "
                  "\"Trained ResNet-50, 87% accuracy. Watch the detection register "
                  "live.\"", step),
        Paragraph("<b>4. Vegetation (NDVI).</b> SHOW the NDVI panel. SAY: \"Live "
                  "Sentinel-2 &mdash; we watch every field's health from orbit, no "
                  "photo needed.\"", step),
        Paragraph("<b>5. Farmland + ShockGuard.</b> SHOW alerts and the flood/"
                  "drought map. SAY: \"Conflict predicted 24 to 72 hours ahead; "
                  "floods seen through cloud by radar.\"", step),
        Paragraph("<b>6. Economic Visibility + SMS.</b> SHOW poverty mapping and "
                  "the multilingual SMS panel. SAY: \"Down to the settlement, and "
                  "out to the farmer by SMS in their language.\"", step),

        Paragraph("The ask", h2),
        Paragraph(
            "\"We'd love to bring NigeriaSat data into this, run a joint "
            "demonstration, and explore a data-sharing MOU. What would be most "
            "useful to your teams?\" &mdash; then <b>listen and take notes</b>.", body),

        Paragraph("If the internet fails", h2),
        Paragraph(
            "Switch to the pitch deck / video without apology. Say: \"I'll send "
            "your team the live link to explore afterwards.\" Never let a "
            "connection issue stall the conversation.", body),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.5, color=BROWN, spaceAfter=4),
        footer_line(),
    ]
    SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="EconomicBridge - Live Demo Script",
    ).build(story)
    shutil.copy(out, DOWNLOADS / out.name)
    return out


if __name__ == "__main__":
    for p in (build_one_pager(), build_demo_script()):
        print(f"  wrote {p.name} ({p.stat().st_size} bytes); copied to Downloads")
