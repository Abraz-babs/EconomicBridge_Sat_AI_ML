"""Pre-season risk profile — the PDF an insurer receives, on the company letterhead.

Same letterhead as the claims report (directors' standard of 24 July 2026).
Contents, as approved 2026-10-10: summary, maps, the LGA table, how we report
and the method, then one appendix block per LGA. The maps are drawn from the
simplified LGA outlines the job stores with each round, so the PDF needs no
GIS library; the farmland-in-flood-zone layer is the job's own mask.

Limits are stated as "How we report", never as a disclaimer list.
"""
from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from services.claims_report import FOOTER_LINES, LOGO
from services.risk_profile import (
    BAND_LABEL, BAND_ORDER, RULE, ha, onset_text, pc, plain_sentences, season_span,
)

PALETTE = {
    "flood": {"high": "#4f7fb0", "moderate": "#a9c4de", "low": "#e3ebf2", "none": "#eeeeee"},
    "drought": {"high": "#9a5a12", "moderate": "#dcae55", "low": "#f2e8cf", "none": "#eeeeee"},
    "rains": {"high": "#9b3f2b", "moderate": "#de9a7c", "low": "#f6e6dc", "none": "#eeeeee"},
}
ZONE_RGB = (29, 53, 87)

HOW_WE_REPORT = [
    "Flood zones are modelled: the JRC/Copernicus GloFAS river flood maps (about 90 m) show where rivers flood "
    "in a 1-in-10 and a 1-in-100-year flood. They cover the larger rivers; flash floods from local downpours and "
    "waterlogging on flat fields are carried by the mapped floods and our disaster register.",
    "Mapped floods are observed: UNOSAT drew them from NOAA VIIRS imagery at 375 m, keeping only new water. Cloud "
    "can hide water, so each figure is the least that was under water, and we print how much of the LGA cloud "
    "covered. UNOSAT lists these maps as not yet field-validated.",
    "Seasons come from CHIRPS v3 monthly rainfall averaged over each LGA. The season is the months that averaged at "
    "least 50 mm in 1991-2020; normal is the 1991-2020 median season total.",
    "Failed rains come from CHIRPS v3 daily rainfall (the station-blended five-day totals spread across days with "
    "NASA IMERG), averaged over the LGA. The rains set in on the first day, from the start of the season, when "
    "three days bring at least 20 mm with no dry spell longer than 7 days in the next 30 (Sivakumar, 1988, as used "
    "by AGRHYMET). A false start is such a rain followed by a longer dry spell; a long dry spell is 10 or more days "
    "under 1 mm in the 30-90 days after the rains set in; a late onset is 20 or more days after the usual date. "
    "Rainfall is averaged over the LGA, so a dry spell counts only when nearly the whole LGA stays dry; local dry "
    "spells are shorter or missed. Where a state has two rainy seasons (southern Ghana), the season figures count both "
    "and the onset and dry spells describe the first.",
    "Farmland is the ESA WorldCover 2021 cropland class (10 m, counted on the 90 m flood grid). It is one snapshot: "
    "fallow or grazed fields can read as grassland, and farms under trees (cocoa, oil palm) as tree cover. Where less "
    "than 5% of an LGA is mapped as farmland, its flood band reads the share of its land instead, and says so. People "
    "are the HRSL 30 m population assigned to GRID3 villages (Nigerian states).",
    "The bands follow one published rule in every state, so a High in one state means the same as in another.",
]

CREDITS = [
    "Rainfall: CHIRPS v3.0, Climate Hazards Center, UC Santa Barbara (CC BY 4.0).",
    "Flood hazard: © European Union, JRC, Copernicus Emergency Management Service, GloFAS flood hazard maps v2.1.2 "
    "(CC BY 4.0); resampled and summarised by LGA.",
    "Farmland: © ESA WorldCover project 2021, contains modified Copernicus Sentinel data (2021) processed by the ESA "
    "WorldCover consortium (CC BY 4.0).",
    "Flood extents: UNOSAT, derived from NOAA VIIRS. Boundaries: geoBoundaries (CC BY 4.0).",
    "Villages and population: GRID3 Nigeria (CC BY 4.0); Meta and CIESIN High Resolution Settlement Layer (CC BY 4.0).",
]


@dataclass
class RiskReport:
    prepared_for: str
    reference: str
    state: str
    through: int
    method: str
    rows: list[dict]                      # band_* + figures per LGA
    summary: dict
    overlays: dict[str, dict] = field(default_factory=dict)   # layer -> {bounds, png (bytes)}


def _outline_parts(geom: dict) -> list[list]:
    if not geom:
        return []
    return [geom["coordinates"]] if geom.get("type") == "Polygon" else list(geom.get("coordinates") or [])


def _bounds(rows: list[dict]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for r in rows:
        for poly in _outline_parts(r["figures"].get("outline")):
            for ring in poly:
                xs += [p[0] for p in ring]
                ys += [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _band_map_flowable(rows: list[dict], kind: str, width: float, height: float,
                       zone: dict | None = None, label: bool = True):
    """A Flowable drawing every LGA filled by its band, with a legend strip."""
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import FILL_EVEN_ODD
    from reportlab.platypus import Flowable

    legend_h = 16.0
    minx, miny, maxx, maxy = _bounds(rows)
    kx = math.cos(math.radians((miny + maxy) / 2))
    s = min(width / ((maxx - minx) * kx), (height - legend_h) / (maxy - miny))
    mw, mh = (maxx - minx) * kx * s, (maxy - miny) * s
    ox, oy = (width - mw) / 2, legend_h + (height - legend_h - mh) / 2

    def px(lon: float) -> float:
        return ox + (lon - minx) * kx * s

    def py(lat: float) -> float:
        return oy + (lat - miny) * s

    overlay = None
    if zone and zone.get("png"):
        from PIL import Image

        m = Image.open(io.BytesIO(zone["png"])).convert("L")
        rgba = Image.new("RGBA", m.size, (*ZONE_RGB, 0))
        rgba.putalpha(m.point(lambda v: 235 if v > 127 else 0))
        overlay = (ImageReader(rgba), zone["bounds"])

    def area(r: dict) -> float:
        b = [p for poly in _outline_parts(r["figures"].get("outline")) for p in poly[0]] if r["figures"].get("outline") else []
        return (max(p[0] for p in b) - min(p[0] for p in b)) * (max(p[1] for p in b) - min(p[1] for p in b)) if b else 0

    order = sorted(rows, key=area, reverse=True)       # big first: an enclave is drawn over its host
    pal = PALETTE[kind]

    class BandMap(Flowable):
        def wrap(self, aw, ah):
            return width, height

        def draw(self):
            c = self.canv
            c.setLineJoin(1)
            for r in order:
                parts = _outline_parts(r["figures"].get("outline"))
                if not parts:
                    continue
                p = c.beginPath()
                for poly in parts:
                    for ring in poly:
                        p.moveTo(px(ring[0][0]), py(ring[0][1]))
                        for pt in ring[1:]:
                            p.lineTo(px(pt[0]), py(pt[1]))
                        p.close()
                c.setFillColor(colors.HexColor(pal.get(r[f"band_{kind}"], pal["none"])))
                c.setStrokeColor(colors.white)
                c.setLineWidth(0.5)
                c.drawPath(p, fill=1, stroke=1, fillMode=FILL_EVEN_ODD)    # holes stay holes
            if overlay:
                img, (w_, s_, e_, n_) = overlay
                c.drawImage(img, px(w_), py(s_), px(e_) - px(w_), py(n_) - py(s_), mask="auto")
            if label and len(rows) <= 40:
                c.setFont("Times-Roman", 6.5)
                for r in rows:
                    cen = r["figures"].get("centroid")
                    if not cen:
                        continue
                    x, y = px(cen[0]), py(cen[1]) - 2
                    # A halo without text render modes (a stroke mode leaks into later text):
                    # the label in white, nudged in eight directions, then in ink on top.
                    c.setFillColor(colors.white)
                    for dx, dy in ((-0.7, 0), (0.7, 0), (0, -0.7), (0, 0.7),
                                   (-0.5, -0.5), (0.5, 0.5), (-0.5, 0.5), (0.5, -0.5)):
                        c.drawCentredString(x + dx, y + dy, r["lga"])
                    c.setFillColor(colors.HexColor("#1a1714"))
                    c.drawCentredString(x, y, r["lga"])
            # legend
            c.setFont("Times-Roman", 7.5)
            lx = 0
            items = [(pal["high"], "High"), (pal["moderate"], "Moderate"), (pal["low"], "Low")]
            if overlay:
                items.append(("#%02x%02x%02x" % ZONE_RGB, "Farmland in the 1-in-10-year flood zone"))
            for col, txt in items:
                c.setFillColor(colors.HexColor(col))
                c.setStrokeColor(colors.HexColor("#9aa39d"))
                c.setLineWidth(0.3)
                c.rect(lx, 3, 8, 8, fill=1, stroke=1)
                c.setFillColor(colors.HexColor("#3d3830"))
                c.drawString(lx + 11, 4.5, txt)
                lx += 11 + c.stringWidth(txt, "Times-Roman", 7.5) + 12

    return BandMap()


def render_risk_report(rep: RiskReport, generated_at: datetime | None = None) -> bytes:
    """Build the PDF. reportlab is imported lazily, as in the claims report."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        CondPageBreak, HRFlowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
        TableStyle,
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
    h1 = st("h1", fontName=serif_b, fontSize=16, leading=20, textColor=dgreen, alignment=1, spaceAfter=2)
    h2 = st("h2", fontName=serif_b, fontSize=12.5, leading=16, textColor=dgreen, spaceBefore=10, spaceAfter=4,
            keepWithNext=1)
    h3 = st("h3", fontName=serif_b, fontSize=11, leading=14, spaceBefore=8, spaceAfter=2, keepWithNext=1)
    cell = st("cell", fontSize=8.5, leading=10.5)
    cell_b = st("cellb", fontName=serif_b, fontSize=8.5, leading=10.5)
    cell_r = st("cellr", fontSize=8.5, leading=10.5, alignment=2)

    def band_cell(kind: str, b: str):
        col = PALETTE[kind].get(b, "#888888")
        txt = "#ffffff" if b == "high" else "#1a1714"
        return Paragraph(f'<font color="{txt}">{BAND_LABEL.get(b, b)}</font>', st(
            f"b{kind}{b}", fontSize=8, leading=10, backColor=colors.HexColor(col), alignment=1, borderPadding=1.5))

    def draw_footer(canvas, doc) -> None:
        canvas.saveState()
        w, _ = A4
        canvas.setStrokeColor(hair)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, 58, w - 18 * mm, 58)
        canvas.setFont(serif, 8.5)
        canvas.setFillColor(muted)
        canvas.drawCentredString(w / 2, 44, FOOTER_LINES[0])
        canvas.drawCentredString(w / 2, 32, FOOTER_LINES[1])
        canvas.drawString(18 * mm, 18, f"Pre-season risk profile · {rep.state} · through the {rep.through} season")
        canvas.drawRightString(w - 18 * mm, 18, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=14 * mm, bottomMargin=72,
        title=f"Pre-season risk profile, {rep.state} ({rep.reference})",
        author="Bizra Farms Integrated Nigeria Limited",
    )
    flow: list = []
    S = rep.summary
    rows = sorted(rep.rows, key=lambda r: (BAND_ORDER.get(r["band_flood"], 3),
                                           -((r["figures"].get("flood") or {}).get("rp10_crop_pct") or 0)))

    # Letterhead
    if LOGO.exists():
        iw, ih = ImageReader(str(LOGO)).getSize()
        flow.append(Image(str(LOGO), width=110, height=110 * ih / iw, hAlign="CENTER"))
        flow.append(Spacer(1, 6))
    flow += [
        HRFlowable(width="100%", thickness=1.6, color=dgreen, spaceAfter=8),
        Paragraph("BIZRA FARMS INTEGRATED NIGERIA LIMITED", st("lh", fontName=serif_b, fontSize=13,
                                                               textColor=dgreen, alignment=1)),
        Paragraph("(RC 1929412)", st("rc", alignment=1)),
        Spacer(1, 10),
        Paragraph("Pre-season Risk Profile", h1),
        Paragraph(escape(rep.state), st("sub", fontSize=12, alignment=1, textColor=muted)),
        Spacer(1, 8),
    ]
    rain_years = f"{rows[0]['figures']['rain']['first_year']}–{rep.through}" if rows and rows[0]["figures"].get("rain") else "—"
    daily = next((r["figures"]["rains"]["years"] for r in rows if (r["figures"].get("rains") or {}).get("years")), [])
    meta = [
        ["Prepared for", escape(rep.prepared_for)],
        ["Reference", escape(rep.reference)],
        ["Area", f"{escape(rep.state)}: {S['lgas']} LGAs"],
        ["Seasons read", f"Rainfall {rain_years}; daily rainfall {daily[0]}–{daily[-1]}" if daily else f"Rainfall {rain_years}"],
        ["Generated", generated_at.strftime("%d %B %Y, %H:%M UTC")],
        ["Prepared by", "Bizra Farms Integrated Nigeria Limited, EconomicBridge platform"],
    ]
    t = Table([[Paragraph(a, st("mb", fontName=serif_b, fontSize=9.5, leading=12)),
                Paragraph(b, st("mc", fontSize=9.5, leading=12))] for a, b in meta],
              colWidths=[38 * mm, 136 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, hair), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    flow.append(t)

    # Summary
    flow.append(Paragraph("Summary", h2))
    share = 100 * S["rp10_cropland_ha"] / S["cropland_ha"] if S["cropland_ha"] else 0
    lines = [f"{ha(S['rp10_cropland_ha'])} of the state's {ha(S['cropland_ha'])} of farmland ({share:.1f}%) lies in "
             "the zone where rivers flood about once every 10 years."]
    for m in S.get("mapped") or []:
        lines.append(f"Satellites saw {ha(m['cropland_ha'])} of farmland under flood water on {m['label']}, with water "
                     f"over at least 1% of {m['lgas_with_water']} LGAs.")
    agree = [m for m in S.get("mapped") or [] if m.get("agreement") is not None]
    if agree:
        lines.append("The flood model and the satellite maps were made independently; ranking the LGAs by farmland in "
                     "the 1-in-10-year zone and by water seen gives a rank agreement of "
                     + " and ".join(f"{m['agreement']:.2f} ({m['label']})" for m in agree)
                     + ", where 1.00 would be the same order.")
    if S.get("drought_seasons_max") is not None:
        lines.append(f"Seasons below 80% of normal rainfall: {S['drought_seasons_min']} to {S['drought_seasons_max']} "
                     f"of {S['seasons']} per LGA.")
    if S.get("rains_failed_max") is not None:
        lines.append(f"Seasons with a false start, a late onset or a long dry spell after planting: "
                     f"{S['rains_failed_min']} to {S['rains_failed_max']} of {S['rains_seasons']} per LGA.")
    for ln in lines:
        flow.append(Paragraph(f"• {escape(ln)}", body))
    bt = [[Paragraph("<b>LGAs by band</b>", cell), Paragraph("<b>High</b>", cell_r),
           Paragraph("<b>Moderate</b>", cell_r), Paragraph("<b>Low</b>", cell_r)]]
    for kind, name in (("flood", "Flood"), ("drought", "Drought (seasonal shortfall)"), ("rains", "Failed rains")):
        b = S["bands"][kind]
        if not sum(b.get(x, 0) for x in ("high", "moderate", "low")):
            continue
        bt.append([Paragraph(name, cell)] + [Paragraph(str(b.get(x, 0)), cell_r) for x in ("high", "moderate", "low")])
    t = Table(bt, colWidths=[84 * mm, 30 * mm, 30 * mm, 30 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, hair),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3ef"))]))
    flow += [Spacer(1, 6), t]

    # Maps
    flow.append(PageBreak())
    flow.append(Paragraph("Flood band, with farmland in the 1-in-10-year flood zone", h2))
    flow.append(_band_map_flowable(rows, "flood", 174 * mm, 150 * mm, zone=rep.overlays.get("rp10_farmland")))
    pair = [_band_map_flowable(rows, k, 84 * mm, 82 * mm, label=False) for k in ("drought", "rains")]
    pt = Table([[Paragraph("Drought band (seasonal shortfall)", h3), Paragraph("Failed-rains band", h3)], pair],
               colWidths=[87 * mm, 87 * mm])
    pt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    flow += [Spacer(1, 6), pt]

    # Rule
    flow.append(Paragraph("The band rule", h2))
    for kind, name in (("flood", "Flood"), ("drought", "Drought"), ("rains", "Failed rains")):
        flow.append(Paragraph(f"<b>{name}.</b> {escape(RULE[kind])}", body))

    # Table
    # The table splits across pages; keeping its heading WITH it would push the
    # whole table to a fresh page and leave most of this one empty.
    flow.append(CondPageBreak(60 * mm))
    flow.append(Paragraph("All LGAs", st("h2t", fontName=serif_b, fontSize=12.5, leading=16, textColor=dgreen,
                                         spaceBefore=10, spaceAfter=4)))
    keys = sorted(((k, m.get("label", k)) for k, m in ((rows[0]["figures"].get("flood") or {}).get("mapped") or {}).items()),
                  reverse=True) if rows else []                       # newest map first
    latest = keys[0] if keys else None
    head = ["LGA", "Flood", "Farmland in 1-in-10-yr zone", f"Under water {latest[1]}" if latest else "Under water",
            "Drought", "Seasons below 80%", "Failed rains", "Failed-rain seasons", "Farmland", "People"]
    data = [[Paragraph(f"<b>{h}</b>", cell) for h in head]]
    for r in rows:
        f = r["figures"]
        fl = f.get("flood") or {}
        rain = f.get("rain") or {}
        rains = f.get("rains") or {}
        mk = ((fl.get("mapped") or {}).get(latest[0]) or {}) if latest else {}
        n_seasons = (rain.get("last_year", 0) - rain.get("first_year", 0) + 1) if rain else 0
        data.append([
            Paragraph(escape(r["lga"]), cell), band_cell("flood", r["band_flood"]),
            Paragraph(f"{pc(fl.get('rp10_area_pct'))} of land" if fl.get("basis") == "land"
                      else f"{pc(fl.get('rp10_crop_pct'))} · {ha(fl.get('rp10_crop_ha'))}", cell_r),
            Paragraph(pc(mk.get("area_pct")) if mk else "—", cell_r),
            band_cell("drought", r["band_drought"]),
            Paragraph(f"{len(rain.get('drought_seasons') or [])} of {n_seasons}", cell_r),
            band_cell("rains", r["band_rains"]),
            Paragraph(f"{len(rains.get('failed_seasons') or [])} of {len(rains['years'])}" if rains.get("years") else "—", cell_r),
            Paragraph(ha(f.get("cropland_ha")), cell_r),
            Paragraph(f"{(f.get('exposure') or {}).get('people'):,}" if (f.get("exposure") or {}).get("people") else "—", cell_r),
        ])
    t = Table(data, colWidths=[23 * mm, 15 * mm, 28 * mm, 17 * mm, 15 * mm, 15 * mm, 15 * mm, 14 * mm, 17 * mm, 15 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, hair), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3ef")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5)]))
    flow.append(t)

    # How we report
    flow.append(Paragraph("How we report", h2))
    for line in HOW_WE_REPORT:
        flow.append(Paragraph(f"• {escape(line)}", body))

    # Appendix
    flow.append(PageBreak())
    flow.append(Paragraph("Appendix: LGA by LGA", h2))
    for r in sorted(rows, key=lambda x: x["lga"]):
        f = r["figures"]
        fl = f.get("flood") or {}
        rain = f.get("rain") or {}
        rains = f.get("rains") or {}
        ex = f.get("exposure") or {}
        facts = [
            ["Farmland", f"{ha(f.get('cropland_ha'))} ({pc(f.get('cropland_pct'), 0)} of the LGA)"],
            ["River flood zones",
             (f"1-in-10-year: {pc(fl.get('rp10_area_pct'))} of the land; 1-in-100-year: {pc(fl.get('rp100_area_pct'))} "
              "(little farmland mapped, so the band reads land)") if fl.get("basis") == "land" else
             (f"1-in-10-year: {pc(fl.get('rp10_crop_pct'))} of farmland ({ha(fl.get('rp10_crop_ha'))}); "
              f"1-in-100-year: {pc(fl.get('rp100_crop_pct'))}, {pc(fl.get('rp100_deep_crop_pct'))} deeper than 1 m")],
        ]
        for _, m in sorted((fl.get("mapped") or {}).items(), reverse=True):
            facts.append([f"Water seen {m.get('label')}",
                          f"{pc(m.get('area_pct'))} of the LGA, {ha(m.get('crop_ha'))} of farmland "
                          f"(cloud hid {pc(m.get('cloud_pct'), 0)})"])
        if rain:
            facts.append(["Rainfall season", f"{season_span(rain.get('season_months') or [])}, normal "
                                             f"{round(rain.get('normal_mm') or 0):,} mm, year-to-year swing "
                                             f"{round(rain.get('cv_pct') or 0)}%"])
            ds = rain.get("drought_seasons") or []
            facts.append(["Seasons below 80%", ", ".join(str(y) for y in ds) if ds else "none"])
        if rains.get("years"):
            facts.append(["Rains usually set in", onset_text(rains.get("onset_median")) or "—"])
            for key, name in (("false_starts", "False starts"), ("late_onsets", "Late onsets"),
                              ("long_dry_spells", "Long dry spells")):
                ys = rains.get(key) or []
                facts.append([name, ", ".join(str(y) for y in ys) if ys else "none"])
        if ex:
            facts.append(["Exposure", f"{ex.get('villages', 0):,} villages, {ex.get('people', 0):,} people, "
                                      f"{ex.get('under5', 0):,} children under five"])
        for e in f.get("register") or []:
            facts.append(["On our disaster register", f"{e.get('date')} · {e.get('type')}: {e.get('name')}"])
        ft = Table([[Paragraph(a, cell_b), Paragraph(escape(b), cell)] for a, b in facts], colWidths=[42 * mm, 132 * mm])
        ft.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, hair), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        bands = (f"Flood {BAND_LABEL.get(r['band_flood'])} · Drought {BAND_LABEL.get(r['band_drought'])} · "
                 f"Failed rains {BAND_LABEL.get(r['band_rains'])}")
        flow.append(KeepTogether([
            Paragraph(f"{escape(r['lga'])}", h3),
            Paragraph(bands, small),
            Paragraph(escape(" ".join(plain_sentences(r["lga"], f))), body),
            Spacer(1, 3), ft, Spacer(1, 4),
        ]))

    # Credits
    flow.append(Paragraph("Sources and credits", h2))
    for c in CREDITS:
        flow.append(Paragraph(escape(c), small))
    flow.append(Paragraph(f"Method {escape(rep.method)}, round through the {rep.through} season.", small))

    doc.build(flow, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


def overlay_bytes(image_data_uri: str) -> bytes:
    return base64.b64decode(image_data_uri.split(",", 1)[1])
