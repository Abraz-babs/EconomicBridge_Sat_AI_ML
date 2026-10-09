"""Satellite claims verification report — the PDF an insurer receives.

Renders the results of the ingestion service's claim check
(apps/ingestion/sources/claim_check.py) for a batch of insured plots, on the
company letterhead (the directors' standard of 24 July 2026: centred logo,
dark-green rule, registered name and RC number, two-line footer).

The wording rules of the claim check carry through to the page: an outcome is
what the satellites saw, never a claim decision. "Not seen by satellite" is
printed with a field-visit recommendation, never as a rejection, and limits
are stated as "How we report" rather than as a disclaimer list.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

LOGO = Path(__file__).resolve().parent.parent / "data" / "bizra-logo.jpg"

OUTCOME_LABEL = {
    "supports": "Consistent with the reported loss",
    "partly_supports": "Partly consistent: field visit recommended",
    "not_supported": "Not seen by satellite: field visit recommended",
    "inconclusive": "Inconclusive: field visit recommended",
}
# Never red: red reads as "rejected", which the report never says.
OUTCOME_COLOUR = {
    "supports": "#136b3a",
    "partly_supports": "#a86b00",
    "not_supported": "#3d5a80",
    "inconclusive": "#6b6b6b",
}
FIELD_VISIT = {"partly_supports", "not_supported", "inconclusive"}

FLOOD_LABEL = {
    "strong": "Open water over much of the plot after the loss date",
    "partial": "Some open water after the loss date",
    "none": "No open-water signal",
    "indeterminate": "Water already present before the loss date",
    "insufficient": "No usable radar pass after the loss date",
}
VEG_LABEL = {
    "marked": "Marked decline",
    "moderate": "Moderate decline",
    "none": "No marked decline",
    "not_assessable": "Little vegetation before the loss date",
    "insufficient": "No usable optical pass before and after",
}

HOW_WE_REPORT = [
    "Every result is evidence from free Copernicus Sentinel satellite data at about 10 m per pixel. It is one input "
    "to the claims decision, never the decision itself.",
    "Radar (Sentinel-1) sees through cloud, day or night, and flags calm open water. Water under tall crop or reeds "
    "can read differently, so where radar sees no water we recommend a field visit rather than a conclusion.",
    "Vegetation (NDVI from Sentinel-2) also falls with harvest and natural maturity, so a decline is read together "
    "with the reported growth stage.",
    "Each claim lists the passes used, with dates and values, and the thresholds applied, so any result can be "
    "re-run and checked.",
]

# Measured, not estimated (validation of 8 Oct 2026, scripts and per-pass
# results kept with the claim-check work). Update this sentence whenever the
# method or the test set changes; never quote a figure that was not measured.
VALIDATION_NOTE = (
    "How this method has been tested: on 24 plots inside floods mapped by the UN Satellite Centre (UNOSAT) in "
    "Kebbi State (September 2024) and Kogi State (October 2022), the satellites showed evidence of the flood on 17 "
    "(11 consistent, 6 partly consistent) and did not see it on 7. None of 12 control plots outside any mapped "
    "flood was flagged. The samples are small and the reference maps are coarse (375 m), so these figures are "
    "indicative; the test will be extended as recorded claim outcomes become available."
)

FOOTER_LINES = (
    "Bizra Farms Integrated Nigeria Limited  •  RC 1929412  •  Kebbi State, Nigeria",
    "bizra@economicbridge.org  •  +234 703 791 9465  •  economicbridge.org  •  "
    "Planting the seeds of Tomorrow",
)


@dataclass
class ReportClaim:
    """One claim in the batch: the insurer's identifiers plus the check result."""

    claim_id: str
    result: dict
    insured_name: str | None = None
    location_note: str | None = None


@dataclass
class ClaimsBatch:
    client_name: str
    batch_ref: str
    claims: list[ReportClaim] = field(default_factory=list)
    validation_note: str | None = None
    # A sample shows the format with real satellite readings but illustrative
    # claim details; every page says so, so it can never pass as a real record.
    sample: bool = False


def outcome_counts(batch: ClaimsBatch) -> dict[str, int]:
    counts = {k: 0 for k in OUTCOME_LABEL}
    for c in batch.claims:
        k = c.result.get("conclusion", "inconclusive")
        counts[k if k in counts else "inconclusive"] += 1
    return counts


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.0f}%" if pct else f"{v:.2f}"


def render_claims_report(batch: ClaimsBatch, generated_at: datetime | None = None) -> bytes:
    """Build the PDF. Imported lazily so the rest of the service doesn't pay
    for reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        CondPageBreak, HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    generated_at = generated_at or datetime.now(timezone.utc)
    dgreen = colors.HexColor("#136b3a")
    ink = colors.HexColor("#111111")
    muted = colors.HexColor("#5b6b60")
    hair = colors.HexColor("#c9d3cd")
    serif, serif_b = "Times-Roman", "Times-Bold"

    def st(name: str, **kw) -> ParagraphStyle:
        base = {"fontName": serif, "fontSize": 10.5, "leading": 14, "textColor": ink}
        base.update(kw)
        return ParagraphStyle(name, **base)

    body = st("body")
    small = st("small", fontSize=9, leading=12, textColor=muted)
    h1 = st("h1", fontName=serif_b, fontSize=16, leading=20, textColor=dgreen, alignment=1, spaceAfter=4)
    h2 = st("h2", fontName=serif_b, fontSize=12.5, leading=16, textColor=dgreen, spaceBefore=10, spaceAfter=4,
            keepWithNext=1)
    cell = st("cell", fontSize=9.5, leading=12)
    cell_b = st("cellb", fontName=serif_b, fontSize=9.5, leading=12)

    def draw_footer(canvas, doc) -> None:
        canvas.saveState()
        w, h = A4
        if batch.sample:
            canvas.setFont(serif_b, 64)
            canvas.setFillColor(colors.Color(0.8, 0.85, 0.82, alpha=0.35))
            canvas.translate(w / 2, h / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "SAMPLE")
            canvas.rotate(-35)
            canvas.translate(-w / 2, -h / 2)
        canvas.setStrokeColor(hair)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, 58, w - 18 * mm, 58)
        canvas.setFont(serif, 8.5)
        canvas.setFillColor(muted)
        canvas.drawCentredString(w / 2, 44, FOOTER_LINES[0])
        canvas.drawCentredString(w / 2, 32, FOOTER_LINES[1])
        canvas.drawRightString(w - 18 * mm, 18, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=14 * mm, bottomMargin=72,
        title=f"Satellite claims verification report {batch.batch_ref}",
        author="Bizra Farms Integrated Nigeria Limited",
    )
    flow: list = []

    # Letterhead
    if LOGO.exists():
        iw, ih = ImageReader(str(LOGO)).getSize()
        flow.append(Image(str(LOGO), width=120, height=120 * ih / iw, hAlign="CENTER"))
        flow.append(Spacer(1, 6))
    flow += [
        HRFlowable(width="100%", thickness=1.6, color=dgreen, spaceAfter=8),
        Paragraph("BIZRA FARMS INTEGRATED NIGERIA LIMITED", st("lh", fontName=serif_b, fontSize=13,
                                                               textColor=dgreen, alignment=1)),
        Paragraph("(RC 1929412)", st("rc", alignment=1)),
        Spacer(1, 12),
        Paragraph("Satellite Claims Verification Report", h1),
        Spacer(1, 6),
    ]
    if batch.sample:
        flow.append(Paragraph(
            "<b>Sample report.</b> The satellite readings are real; the claim numbers, names and loss dates are "
            "illustrative, to show the format. It is not a record of any real claim.",
            st("sample_note", textColor=colors.HexColor("#a86b00"), alignment=1)))
        flow.append(Spacer(1, 6))

    meta = [
        ["Prepared for", escape(batch.client_name)],
        ["Batch reference", escape(batch.batch_ref)],
        ["Claims in this batch", str(len(batch.claims))],
        ["Generated", generated_at.strftime("%d %B %Y, %H:%M UTC")],
        ["Prepared by", "Bizra Farms Integrated Nigeria Limited, EconomicBridge platform"],
        ["Satellite data", "Copernicus Sentinel-1 (radar) and Sentinel-2 (optical), via the Copernicus Data Space"],
    ]
    t = Table([[Paragraph(a, cell_b), Paragraph(b, cell)] for a, b in meta], colWidths=[45 * mm, 129 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, hair), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow.append(t)

    # Summary
    counts = outcome_counts(batch)
    flow.append(Paragraph("Summary", h2))
    rows = [[Paragraph("<b>Outcome</b>", cell), Paragraph("<b>Claims</b>", cell)]]
    for k, label in OUTCOME_LABEL.items():
        rows.append([Paragraph(f'<font color="{OUTCOME_COLOUR[k]}"><b>{label}</b></font>', cell),
                     Paragraph(str(counts[k]), cell)])
    visits = sum(counts[k] for k in FIELD_VISIT)
    rows.append([Paragraph("<b>Field visits recommended</b>", cell), Paragraph(f"<b>{visits}</b>", cell)])
    t = Table(rows, colWidths=[130 * mm, 44 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, hair),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3ef"))]))
    flow.append(t)

    # How we report
    flow.append(Paragraph("How we report", h2))
    for line in HOW_WE_REPORT:
        flow.append(Paragraph(f"• {escape(line)}", body))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(escape(batch.validation_note or VALIDATION_NOTE), small))

    # Per claim
    flow.append(CondPageBreak(70 * mm))   # never strand the heading at a page foot
    flow.append(Paragraph("Claims", h2))
    for c in batch.claims:
        r = c.result
        k = r.get("conclusion", "inconclusive")
        m = r.get("metrics") or {}
        head = f"<b>Claim {escape(c.claim_id)}</b>"
        if c.insured_name:
            head += f" &nbsp;•&nbsp; {escape(c.insured_name)}"
        if c.location_note:
            head += f" &nbsp;•&nbsp; {escape(c.location_note)}"
        evidence = [
            ["Plot", f"{r.get('lat', 0):.5f}, {r.get('lon', 0):.5f}  ({r.get('area_ha', '?')} ha checked)"],
            ["Peril and loss date", f"{str(r.get('peril', '')).title()}, {r.get('loss_date', '')}"],
            ["Before window", str((r.get('windows') or {}).get('before', '—'))],
            ["After window", str((r.get('windows') or {}).get('after', '—'))],
            ["Radar, open water", f"{FLOOD_LABEL.get(r.get('flood_evidence'), '—')}: "
                                  f"{_fmt(m.get('water_share_before'), True)} of plot before, "
                                  f"{_fmt(m.get('water_share_after_peak'), True)} at peak after"],
            ["Vegetation (NDVI)", f"{VEG_LABEL.get(r.get('vegetation_change'), '—')}: "
                                  f"{_fmt(m.get('ndvi_before'))} before, {_fmt(m.get('ndvi_after_low'))} "
                                  f"after (level held on at least two passes)"],
        ]
        passes = (
            [f"{p['date']} water {p['water_share'] * 100:.0f}% ({p['window']})" for p in r.get("water_passes", [])]
            + [f"{p['date']} NDVI {p['ndvi']:.2f} ({p['window']})" for p in r.get("ndvi_passes", [])]
        )
        et = Table([[Paragraph(a, cell_b), Paragraph(escape(b), cell)] for a, b in evidence],
                   colWidths=[40 * mm, 134 * mm])
        et.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, hair), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        block = [
            Paragraph(head, st("ch", fontSize=11, leading=14, spaceBefore=8)),
            Paragraph(f'<font color="{OUTCOME_COLOUR.get(k, "#6b6b6b")}"><b>'
                      f'{OUTCOME_LABEL.get(k, OUTCOME_LABEL["inconclusive"])}</b></font>', body),
            Paragraph(escape(r.get("summary", "")), body),
            Paragraph(f"<i>{escape(r.get('recommendation', ''))}</i>", body),
            Spacer(1, 3), et,
        ]
        if passes:
            block.append(Paragraph("Passes used: " + escape("; ".join(passes)), small))
        flow.append(KeepTogether(block))

    # Method + attribution
    years = sorted({str(c.result.get("loss_date", ""))[:4] for c in batch.claims if c.result.get("loss_date")})
    th = (batch.claims[0].result.get("thresholds") if batch.claims else None) or {}
    flow.append(Paragraph("Method", h2))
    flow.append(Paragraph(
        "For each plot, the satellite passes from 60 to 15 days before the loss date (its normal state) are "
        "compared with those from 14 days before to 30 days after it. The comparison window opens before the "
        "reported date because floods build up over days and losses are often reported after the water arrives. "
        "Radar marks a pixel as open water when its VV backscatter is below "
        f"{th.get('water_vv_db_below', -17.0)} dB; a flood signal is graded strong when at least "
        f"{_fmt(th.get('flood_strong_share'), True)} of the plot reads as water after the loss and was not "
        "before. Optical passes are used only where clouds leave at least a quarter of the plot visible.", body))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(
        f"Contains modified Copernicus Sentinel data {', '.join(years) if years else ''}, processed by "
        "Bizra Farms Integrated Nigeria Limited.", small))

    doc.build(flow, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()
