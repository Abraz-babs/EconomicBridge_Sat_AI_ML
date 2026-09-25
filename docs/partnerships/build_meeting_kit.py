"""Generate the NASRDA meeting kit: a one-page executive leave-behind, a
one-page live-demo script and a one-page EO-landscape comparison. All three on
the company letterhead, portrait A4, print-ready.

Rebuilt for the 2 October 2026 meeting from measured figures only. The June
versions quoted 700+ LGAs, an unqualified 87.2% model accuracy, conflict
"predicted 24 to 72 hours ahead" and floods "seen through cloud by radar".
Our own later measurement contradicts each of those (the 2024 Kebbi flood
backtest scored 0 of 11), so none of them may come back. The figures here
match EconomicBridge_DG_Briefing.md; change them there first.

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_meeting_kit.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).parent))
from _letterhead import (  # noqa: E402
    BOTTOM_MARGIN, DGREEN, INK, SERIF, SERIF_B, draw_footer, letterhead,
)

HERE = Path(__file__).parent
DOWNLOADS = Path(r"C:\Users\HP\Downloads")

# Register a glyph font that has check/cross/half symbols (Times lacks
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
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef6f0")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontName=SERIF, fontSize=10.3,
                      leading=13.6, textColor=INK, alignment=TA_JUSTIFY,
                      spaceAfter=5)
lead = ParagraphStyle("lead", parent=body, fontSize=11.5, leading=15,
                      alignment=0, spaceAfter=8)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName=SERIF_B, fontSize=12.5,
                    leading=15.5, textColor=DGREEN, spaceBefore=8, spaceAfter=3)
small = ParagraphStyle("small", parent=body, fontSize=8.8, leading=11.5,
                       textColor=GREY, alignment=0, spaceAfter=0)
bignum = ParagraphStyle("bignum", parent=ss["Normal"], fontName=SERIF_B,
                        fontSize=22, leading=25, textColor=GREEN, alignment=1)
numlbl = ParagraphStyle("numlbl", parent=ss["Normal"], fontName=SERIF,
                        fontSize=8.4, leading=10, textColor=INK, alignment=1)
step = ParagraphStyle("step", parent=body, alignment=0, spaceAfter=6)


def _build(out: Path, story: list, title: str, side_mm: float = 18) -> Path:
    SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=side_mm * mm, rightMargin=side_mm * mm,
        topMargin=12 * mm, bottomMargin=BOTTOM_MARGIN, title=title,
        author="Bizra Farms Integrated Nigeria Limited",
    ).build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    shutil.copy(out, DOWNLOADS / out.name)
    return out


# EO competitor comparison. Honest: ✓ full · ◑ partial · ✗ none. Columns:
# EconomicBridge, Planet/Maxar, EOS/Farmonaut, Digital Earth Africa.
# EconomicBridge's own partial marks are measured, not modest: the disease
# model has passed laboratory images only, the 2024 Kebbi flood backtest
# scored 0 of 11 (so it reports storms and extreme rain, not floods), and aid
# coverage is what organisations publish to IATI (since 2026-09-25; HDX covers
# only the north-east) — reported activity, not all aid, so still partial.
_CAPS = [
    ("AI crop-disease diagnosis (from a leaf photo)", "pnnn"),
    ("Satellite crop / vegetation monitoring (NDVI)", "yyyy"),
    ("Flood & drought early warning", "pyny"),
    ("Farmer-herder conflict & encroachment warning", "ynnn"),
    ("Poverty & population mapping", "ypnp"),
    ("Aid-coordination & multi-agency coverage", "pnnn"),
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
    capc = ParagraphStyle("capc", parent=ss["Normal"], fontName=SERIF,
                          fontSize=9, leading=10.8, textColor=INK)
    hdr = ParagraphStyle("hdrc", parent=ss["Normal"], fontName=SERIF_B,
                         fontSize=8, leading=9.2, textColor=colors.white,
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


# ─── 1. One-page executive leave-behind ───────────────────────────────────
def build_one_pager():
    story = letterhead() + [
        Spacer(1, 10),
        Paragraph("EconomicBridge — Executive Brief", h2),
        Paragraph(
            "A live satellite and AI platform that turns Earth observation into "
            "decisions for agriculture, food security and disaster response. "
            "Built and operated in Nigeria by Bizra Farms Integrated Nigeria "
            "Limited.", lead),
    ]
    stats = [
        [Paragraph("142", bignum), Paragraph("18.3M", bignum),
         Paragraph("64%", bignum), Paragraph("8", bignum)],
        [Paragraph("LGAs read pixel by pixel", numlbl),
         Paragraph("hectares of farmland greening, 2026 rains", numlbl),
         Paragraph("change precision, random sample", numlbl),
         Paragraph("live data feeds", numlbl)],
    ]
    t = Table(stats, colWidths=[43 * mm] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.white),
    ]))
    story += [
        t, Spacer(1, 4),
        Paragraph(
            "Farmland: cropland and rangeland on Esri's 2023 land-cover map; "
            "tree canopy and built-up land excluded. Precision: of the land "
            "changes the platform reports, the share confirmed by eye against "
            "before-and-after Sentinel-2 imagery on a random sample (95% "
            "interval 45–80%). Validation against the ground is the next "
            "step.", small),
        Spacer(1, 4),

        Paragraph("What it does", h2),
        Paragraph(
            "<b>Farmland Protection</b> — every pixel of every pilot LGA read each "
            "rainy season, and each land change on cropland or rangeland reported "
            "at its own coordinates, for early warning of encroachment and "
            "farmer-herder conflict. &nbsp; <b>ShockGuard</b> — storms and extreme "
            "rainfall rebuilt from half-hourly NASA satellite rainfall. &nbsp; "
            "<b>CropGuard</b> — crop-disease diagnosis from a leaf photo, "
            "validated on laboratory images, plus satellite vegetation "
            "monitoring. &nbsp; <b>Economic Visibility</b> — poverty and "
            "population mapping from space. &nbsp; Plus mobility and education "
            "intelligence. Rainfall advisories reach farmer "
            "cooperative leaders in Kebbi by SMS in Hausa, no smartphone needed.",
            body),

        Paragraph("Built on", h2),
        Paragraph(
            "Open data from Copernicus Sentinel-1 and Sentinel-2, NASA, Esri land "
            "cover, the World Bank, UNICEF and WorldPop; a trained ResNet-50 model "
            "plus land-change and anomaly detection; running on AWS with "
            "multi-tenant data isolation and honest measured-versus-modelled "
            "labelling.", body),

        Paragraph("Proposed collaboration with NASRDA", h2),
        Paragraph(
            "&bull; A <b>single-state data pilot</b>: NigeriaSat / NCRS imagery "
            "for one cloud-limited state (Benue is the clearest case), measured "
            "against the same random-sample standard.<br/>"
            "&bull; <b>Ground-truth validation</b>: NASRDA field data to validate "
            "the land-change detector and the crop-disease model in the "
            "field.<br/>"
            "&bull; A live <b>reference platform</b> for NASRDA's application "
            "centres.<br/>"
            "&bull; A path to a <b>data-sharing memorandum of understanding</b>.",
            body),
    ]
    return _build(HERE / "Bizra_NASRDA_OnePager.pdf", story,
                  "EconomicBridge - Executive Brief (NASRDA)")


# ─── 2. One-page live-demo script ─────────────────────────────────────────
# Same running order as the (local-only) meeting prep, minus its candid notes:
# this PDF sits in a public repository.
def build_demo_script():
    story = letterhead() + [
        Spacer(1, 10),
        Paragraph("Live Demo Script — NASRDA Meeting", h2),
        Paragraph(
            "Aim: walk out with a committed next step, a one-state data pilot "
            "(Benue) and a path to a data-sharing MOU. Let the live product do "
            "the talking; keep it to five minutes, then listen.", body),

        Paragraph("Pre-flight (before you walk in)", h2),
        Paragraph(
            "&bull; Phone hotspot ON and tested on economicbridge.org (do not "
            "trust venue wifi).<br/>"
            "&bull; Browser full-screen (F11), logged in as super-admin, Overview "
            "and Farmland Protection on Kebbi pre-loaded.<br/>"
            "&bull; Screenshots of the Ngaski and Maiyama detections and the "
            "pitch deck PDF saved offline as a fallback.<br/>"
            "&bull; CropGuard only if asked, on a laboratory image pre-tested so "
            "it reads as a disease. Never test on a leaf handed to you in the "
            "room: the model is validated on laboratory images, not field "
            "photographs.", body),

        Paragraph("The walkthrough", h2),
        Paragraph("<b>1. Overview (0:00).</b> SHOW the live map. SAY: \"Live and "
                  "multi-tenant: 142 LGAs across eight Nigerian pilot "
                  "territories, read from open Copernicus and NASA data.\"", step),
        Paragraph("<b>2. Farmland Protection, Kebbi (0:30).</b> SHOW Ngaski or "
                  "Maiyama. SAY: \"Each of these is a separate patch at its own "
                  "coordinates, eleven in Ngaski alone, not one pin at the "
                  "centre. This one greened in 2024 and 2025 and stayed bare "
                  "through this year's rains.\"", step),
        Paragraph("<b>3. The accuracy question (2:00).</b> SAY: \"Before you ask "
                  "how often it is right: 64% on a random sample, checked by eye "
                  "against before-and-after imagery. We tested a looser rule; it "
                  "scored 2 in 55, so we don't ship it.\"", step),
        Paragraph("<b>4. ShockGuard (3:00).</b> SHOW the storm map. SAY: \"Storms "
                  "rebuilt from half-hourly NASA rainfall, filed by the day the "
                  "rain actually fell. We tested flood detection against the "
                  "2024 Kebbi floods and it did not detect them, so we do not "
                  "claim it.\"", step),
        Paragraph("<b>5. Rainfall advisories (4:00).</b> SAY: \"Every morning "
                  "each Kebbi LGA's rainfall is checked against its own history. "
                  "When it crosses the extreme threshold, farmer cooperative "
                  "leaders get an SMS in Hausa, automatically, with no one in "
                  "the loop.\"", step),

        Paragraph("The ask (4:30)", h2),
        Paragraph(
            "\"Where we need NASRDA is the cloudy south and the ground truth. "
            "Could we agree a one-state data pilot, Benue, and a path to a "
            "data-sharing MOU? What would be most useful to your teams?\" Then "
            "<b>listen and take notes</b>.", body),

        Paragraph("If the internet fails", h2),
        Paragraph(
            "Switch to the saved screenshots and deck without apology. Say: "
            "\"I'll send your team the live link to explore afterwards.\" Never "
            "let a connection issue stall the conversation.", body),
    ]
    return _build(HERE / "EconomicBridge_Demo_Script.pdf", story,
                  "EconomicBridge - Live Demo Script")


# ─── 3. Standalone EO-landscape comparison sheet ──────────────────────────
def build_comparison_sheet():
    story = letterhead() + [
        Spacer(1, 10),
        Paragraph("EconomicBridge in the Earth-Observation Landscape", h2),
        Paragraph(
            "EconomicBridge competes on the applied-intelligence and last-mile "
            "layer over open Copernicus/NASA data — turning satellite data into "
            "decisions and alerts that reach the farmer. Compared with the major "
            "EO providers:", body),
        Spacer(1, 4),
        _comparison_table(),
        Spacer(1, 5),
        Paragraph(
            f"{_legend()} EconomicBridge's partial marks are its own "
            "measurement: the crop-disease model is validated on laboratory "
            "images and awaits field validation, the platform reports storms "
            "and extreme rainfall rather than floods, and its aid-coordination "
            "feed holds no records for the pilot states yet. EconomicBridge does "
            "not own satellites; national space assets such as NASRDA's "
            "NigeriaSat and NCRS archives are its natural complement, not a "
            "competitor.", small),
    ]
    return _build(HERE / "EconomicBridge_EO_Comparison.pdf", story,
                  "EconomicBridge - EO Landscape Comparison", side_mm=16)


if __name__ == "__main__":
    for p in (build_one_pager(), build_demo_script(), build_comparison_sheet()):
        print(f"  wrote {p.name} ({p.stat().st_size} bytes); copied to Downloads")
