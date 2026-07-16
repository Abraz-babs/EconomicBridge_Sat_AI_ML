"""EO Engine Brief — presenter's prep document (PDF).

How every satellite and model in the EconomicBridge engine works, what the
physics honestly allows, and what our engine actually does with it — plus
the approved answers to hard expert questions. Written for pre-meeting
preparation (NASRDA / NSIA / state / investor).

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_eo_engine_brief.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\HP\Downloads\EconomicBridge_EO_Engine_Brief.pdf")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

DGREEN = colors.HexColor("#0a5c2e")
GREEN = colors.HexColor("#1f8a3b")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
TINT = colors.HexColor("#f0f7f2")
AMBER = colors.HexColor("#b97c10")
RED = colors.HexColor("#b3402a")

BODY, BODY_B = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("EB", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBB", r"C:\Windows\Fonts\arialbd.ttf"))
    BODY, BODY_B = "EB", "EBB"
except Exception:  # noqa: BLE001
    pass

W, H = A4
X0, X1 = 40, W - 40


def wrap(c, text, font, size, maxw):
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


class Doc:
    def __init__(self, path, title, sub):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.title, self.sub = title, sub
        self.page = 0
        self._new_page()

    def _new_page(self):
        if self.page > 0:
            self._footer()
            self.c.showPage()
        self.page += 1
        y = H - 44
        if self.page == 1 and LOGO.exists():
            try:
                from reportlab.lib.utils import ImageReader
                ir = ImageReader(str(LOGO))
                iw, ih = ir.getSize()
                self.c.drawImage(ir, X0, y - 8, width=36, height=36 * ih / iw, mask="auto")
            except Exception:  # noqa: BLE001
                pass
        self.c.setFillColor(DGREEN)
        self.c.setFont(BODY_B, 14.5 if self.page == 1 else 10.5)
        self.c.drawString(X0 + (44 if self.page == 1 else 0),
                          y + (8 if self.page == 1 else 0),
                          self.title if self.page == 1 else f"{self.title} (p. {self.page})")
        if self.page == 1:
            self.c.setFillColor(MUTED)
            self.c.setFont(BODY, 8.6)
            self.c.drawString(X0 + 44, y - 6, self.sub)
        self.y = y - 30

    def _footer(self):
        self.c.setFillColor(MUTED)
        self.c.setFont(BODY, 7.2)
        self.c.drawCentredString((X0 + X1) / 2, 26,
                                 "EconomicBridge · EO Engine Brief · internal presenter prep · "
                                 f"15 July 2026 · p. {self.page}")

    def guard(self, need=64):
        if self.y < need:
            self._new_page()

    def section(self, label, accent=GREEN):
        self.guard(100)
        self.c.setFillColor(TINT)
        self.c.setStrokeColor(accent)
        self.c.setLineWidth(0.8)
        self.c.roundRect(X0, self.y - 16, X1 - X0, 19, 4, stroke=1, fill=1)
        self.c.setFillColor(DGREEN)
        self.c.setFont(BODY_B, 9.8)
        self.c.drawString(X0 + 7, self.y - 10.5, label)
        self.y -= 28

    def para(self, text, size=8.7, leading=11.4, bold_head=None, color=INK, indent=0):
        self.guard()
        maxw = X1 - X0 - indent
        full = (bold_head + " " + text) if bold_head else text
        lines = wrap(self.c, full, BODY, size, maxw)
        for i, ln in enumerate(lines):
            self.guard()
            if i == 0 and bold_head:
                self.c.setFont(BODY_B, size)
                self.c.setFillColor(color)
                self.c.drawString(X0 + indent, self.y, bold_head)
                off = pdfmetrics.stringWidth(bold_head + " ", BODY_B, size)
                self.c.setFont(BODY, size)
                self.c.setFillColor(INK)
                self.c.drawString(X0 + indent + off, self.y, ln[len(bold_head):].lstrip())
            else:
                self.c.setFont(BODY, size)
                self.c.setFillColor(INK)
                self.c.drawString(X0 + indent, self.y, ln)
            self.y -= leading
        self.y -= 2.5

    def sensor(self, name, spec, how, gives, limits):
        """A sensor/model block: bold name + spec line, then 3 labelled paras."""
        self.guard(120)
        self.c.setFillColor(DGREEN)
        self.c.setFont(BODY_B, 10)
        self.c.drawString(X0, self.y, name)
        self.c.setFillColor(MUTED)
        self.c.setFont(BODY, 8)
        self.c.drawString(X0 + pdfmetrics.stringWidth(name, BODY_B, 10) + 8, self.y, spec)
        self.y -= 13
        self.para(how, bold_head="How it works:", indent=8)
        self.para(gives, bold_head="What it gives us:", indent=8, color=GREEN)
        self.para(limits, bold_head="Honest limits:", indent=8, color=AMBER)
        self.y -= 4

    def table(self, headers, rows, widths, size=7.9, leading=10):
        """3-col wrapped table."""
        self.guard(80)
        xs = [X0]
        for wd in widths[:-1]:
            xs.append(xs[-1] + wd)
        # header
        self.c.setFont(BODY_B, size)
        self.c.setFillColor(MUTED)
        for x, h_, wd in zip(xs, headers, widths):
            self.c.drawString(x, self.y, h_)
        self.y -= leading + 3
        for cells in rows:
            wrapped = [wrap(self.c, cell, BODY, size, wd - 8)
                       for cell, wd in zip(cells, widths)]
            nlines = max(len(wl) for wl in wrapped)
            self.guard(nlines * leading + 14)
            self.c.setFont(BODY, size)
            for x, wl, wd in zip(xs, wrapped, widths):
                self.c.setFillColor(INK)
                for j, ln in enumerate(wl):
                    if x == xs[0] and j == 0:
                        self.c.setFont(BODY_B, size)
                        self.c.drawString(x, self.y - j * leading, ln)
                        self.c.setFont(BODY, size)
                    else:
                        self.c.drawString(x, self.y - j * leading, ln)
            self.y -= nlines * leading + 5
            self.c.setStrokeColor(colors.HexColor("#e2e8e4"))
            self.c.setLineWidth(0.4)
            self.c.line(X0, self.y + 2, X1, self.y + 2)
            self.y -= 4

    def save(self):
        self._footer()
        self.c.showPage()
        self.c.save()


d = Doc(OUT, "EconomicBridge — How the EO Engine Sees",
        "Presenter's brief: every satellite and model, what the physics allows, what we honestly claim · prep before any expert meeting")

# ── 1. Engine in 60 seconds ────────────────────────────────────────────────
d.section("1. THE ENGINE IN 60 SECONDS")
d.para("EconomicBridge fuses several INDEPENDENT satellite signals per Local Government Area, every day, "
       "unattended. No single signal is trusted alone: radar says the ground surface changed, optical says "
       "vegetation declined, thermal says something burned, night-lights say people arrived. When independent "
       "signals agree abnormally, the engine raises a WATCH for a human to verify. The engine narrows WHERE to "
       "look; field officers confirm WHAT happened. Every alert carries its provenance (which satellites, which "
       "passes, what confidence) and requires_human_review=true. This is the same architecture used by credible "
       "global systems (FEWS NET, Copernicus EMS) — anomaly detection plus human confirmation, never robot verdicts.")
d.para("The one-line defence of the whole design: at 10-metre resolution nobody can honestly claim to identify "
       "actors from orbit — but land does not lie about being disturbed, and disturbance seen early is decision "
       "time bought for a government.", bold_head="Why fusion:")

d.para("we hold credentials to the two doors behind the world's civilian EO archives — "
       "Copernicus CDSE for the European fleet (Sentinel-1/2, Statistical API) and NASA Earthdata for the "
       "American one (LAADS night-lights today; the same single token already proven against NSIDC for SMAP "
       "soil moisture, with GPM rainfall, GRACE groundwater and the MODIS land products behind the same door). "
       "Both free, both integrated. When asked 'can you add X?', the honest answer is usually: the data for X "
       "is behind a door we already hold the key to. Supply is not our risk.",
       bold_head="Data access — the two doors:")

d.table(
    ["Sensor / feed", "Measures", "Res / revisit · role"],
    [
        ["Sentinel-1 SAR (ESA)", "Radar backscatter — surface roughness & moisture; sees through cloud, day/night",
         "10 m · ~6 days · disturbance + flood core"],
        ["Sentinel-2 optical (ESA)", "NDVI vegetation vigour (red vs near-infrared reflectance), per-pixel cloud-masked",
         "10 m · ~5 days (cloud-limited) · vigour + drought + grazing decline"],
        ["NASA FIRMS (VIIRS/MODIS)", "Active-fire thermal anomalies, detected within hours of overpass",
         "375 m · daily · burning / corridor fires"],
        ["NASA VIIRS Black Marble", "Night-time light radiance, moonlight-corrected, gap-filled",
         "~500 m · daily · encampments, settlement, economic activity"],
        ["WorldPop", "Gridded population estimates", "100 m · annual · livelihoods-at-risk numbers"],
        ["Esri/IO 10 m Land Cover", "Annual land classification 2017–2025 (crops/built/rangeland/water)",
         "10 m · yearly · conversion context, not detection"],
        ["Esri World Imagery + Wayback", "High-res reference imagery, archived 2014–2026",
         "sub-m · archive · visual context — labelled NOT detection-time"],
    ],
    [128, 232, 155],
)

# ── 2. Sensors, one by one ────────────────────────────────────────────────
d.section("2. THE SATELLITES — HOW EACH ONE ACTUALLY WORKS")

d.sensor(
    "Sentinel-1 (SAR radar)", "C-band · 10 m · ~6-day revisit · all-weather, day & night",
    "An active sensor: it transmits microwave pulses and measures what bounces back (backscatter). Rough, "
    "disturbed or wet surfaces reflect differently from smooth dry ones. Clouds are transparent to it — the only "
    "all-weather eye we have, which is decisive in the West African wet season.",
    "Land-surface disturbance (clearing, trampling, earthworks) as backscatter shifts vs the location's own "
    "baseline; FLOOD detection as a sharp backscatter DROP (open water reflects the pulse away like a mirror). "
    "Feeds the encroachment watch and ShockGuard flood.",
    "Backscatter also responds to soil moisture, so rainy-season onset can mimic change — our z-scores are "
    "honest but conservative for this reason; the Sep–Oct seasonal-baseline upgrade (3-year history already "
    "banked) tightens exactly this. Cause-agnostic: radar sees THAT the surface changed, never WHO changed it.",
)
d.sensor(
    "Sentinel-2 (optical / NDVI)", "10 m · ~5-day revisit · blocked by cloud",
    "Measures sunlight reflected in red vs near-infrared bands. Healthy chlorophyll absorbs red and reflects "
    "near-infrared strongly; the NDVI ratio (−1..+1) quantifies vegetation vigour per pixel. We mask clouds "
    "per-pixel using the scene classification layer, so a hazy pass contributes only its clear pixels.",
    "Crop vigour (Farm Check single/bulk, per-LGA crop health), vegetation-stress early warning (each plot "
    "against its OWN multi-season baseline), drought signal (sustained NDVI decline), grazing-pressure decline "
    "over weeks.",
    "Cloud-limited: wet-season gaps of 2–3 weeks over a location are normal — the UI states data recency rather "
    "than hiding it. NDVI is a LAGGING drought indicator (plants brown weeks after moisture deficit begins) — "
    "the planned SMAP soil-moisture feed (feasibility proven) is the leading-indicator upgrade. Harvest looks "
    "like vegetation loss too; the crop-calendar filter is on the roadmap.",
)
d.sensor(
    "NASA FIRMS (thermal / active fire)", "VIIRS 375 m + MODIS 1 km · detections within hours · daily",
    "Detects thermal anomalies — pixels significantly hotter than their neighbours — from fires actively burning "
    "at the moment of overpass. It is a fire ALARM, not a burn map.",
    "Burning along movement corridors and near farmland boundaries — a documented precursor in encroachment "
    "dynamics and our most reliable herd-ASSOCIATED signal; daily ingestion feeds the conflict model and the "
    "fire-status line.",
    "375 m pixels cannot sense animal body heat (the patent was deliberately corrected from 'thermal herd "
    "signature' to 'ENCAMPMENT signature' for exactly this honesty). Short fires between overpasses are missed; "
    "gas flares and industrial heat can false-positive; seasonally near-zero in the rains — the dashboard says "
    "'seasonally low' rather than implying a dead feed.",
)
d.sensor(
    "NASA VIIRS Black Marble (night lights)", "VNP46A2 · ~500 m · daily · moonlight-corrected, gap-filled",
    "Measures the radiance of lights on the ground at night, corrected for moonlight and atmosphere. New light "
    "where there was none is people arriving; dimming is activity declining.",
    "Encampment / settlement corroboration for the encroachment watch (a fourth independent signal), and "
    "night-light poverty/economic-visibility mapping.",
    "A ~500 m pixel needs meaningful light — small unlit or firelit camps stay invisible. Light means human "
    "presence, not intent.",
)
d.sensor(
    "Context layers (not detectors)", "WorldPop · Esri/IO 10 m Land Cover · Esri World Imagery/Wayback",
    "Population grids convert hectares into livelihoods-at-risk; annual land-cover classification shows what the "
    "land IS (cropland/built/rangeland) and how it converted year over year; Esri imagery + the 2014–2026 Wayback "
    "archive give visual before/after context.",
    "The Spotlight briefing computes real land-mix percentages around each alert in the browser (e.g. 'built-up "
    "+4.4 pts since 2018 — settlement pressure'); Wayback shows structural change (buildings, roads, field "
    "boundaries) that has no seasonality excuse.",
    "All context, never detection: reference imagery capture dates vary (labelled 'NOT detection-time' in-app); "
    "land cover is annual, not live. Never let a viewer believe the pretty basemap is the detection sensor.",
)

# ── 3. Models ─────────────────────────────────────────────────────────────
d.section("3. THE MODELS — WHAT THE SOFTWARE DOES WITH THE SIGNALS")
d.sensor(
    "Encroachment / land-disturbance watch", "fused · per-LGA · daily 07:00 UTC · requires human review",
    "For each LGA (rolling, revisit-matched): compute how unusual the recent Sentinel-2 NDVI and Sentinel-1 "
    "backscatter are versus that location's own history (z-scores), add recent FIRMS fire counts and VIIRS "
    "new-light corroboration, fuse into one score. Above threshold → a WATCH alert with severity, confidence, "
    "affected-area and livelihoods estimates.",
    "48–72-hour early-warning window for encroachment pressure: grazing, clearing, burning, encampment — the "
    "many faces of land disturbance under one umbrella, surfaced early enough for verification and response.",
    "Cause-agnostic by physics (see the truth table). Confidence scores are honestly modest (50–70%) because "
    "they reflect real uncertainty — they rise through methodology (seasonal baselines) and field verification, "
    "never by decree.",
)
d.sensor(
    "ShockGuard flood & drought detectors", "statistical · daily scan · per-LGA where CDSE-configured",
    "Flood: a sharp DROP in SAR backscatter (open water mirrors the radar pulse away). Drought: sustained NDVI "
    "decline below baseline. Both are z-score detectors against the location's history, scanned daily.",
    "Statewide flood/drought risk signals feeding the dashboard, agency email digests and the Overview.",
    "Drought via NDVI is lagging (see Sentinel-2); flood detection at LGA aggregation flags large open-water "
    "change, not street-level inundation. The U-Net segmentation model is planned once labelled rasters exist — "
    "and we say 'statistical detector' in-app until then.",
)
d.sensor(
    "Farm Check (single + bulk)", "per-coordinate · on-demand · Sentinel-2 NDVI + Sentinel-1 SAR",
    "For any coordinate: read the latest usable cloud-masked NDVI over a tight box (~1.4 ha or ~5.8 ha), grade "
    "vigour (crop-aware when the crop is declared; absolute vigour bands when it is not), show the full pass "
    "history and a stress early-warning comparing the plot against its OWN multi-season baseline.",
    "Field-officer drill-down: verify a specific farm in seconds, singly or as a pasted list (bulk + CSV export). "
    "The place name, analysed-area box and per-pass provenance are all shown.",
    "A vigour snapshot is not a diagnosis: stress signals say 'investigate', the leaf model (below) says what "
    "disease it resembles, and the officer's eyes decide. Wrong-state coordinates are flagged, not silently "
    "accepted.",
)
d.sensor(
    "CropGuard leaf-disease classifier", "ResNet-50 · 12 classes · genuinely trained (val. accuracy 0.872)",
    "A convolutional neural network fine-tuned on labelled leaf photographs. An officer uploads a photo; the "
    "model returns the most likely disease with confidence and top-alternatives.",
    "Ground-level confirmation layer for the satellite stress signal: satellite says WHERE stress is emerging, "
    "the leaf photo says WHAT it looks like.",
    "Validated on public datasets, not yet on Nigerian field photos — it flags low-confidence cases for human "
    "review and will only claim locally-measured accuracy after local labels exist (a stated goal of the NASRDA "
    "collaboration). It suggests; an agronomist confirms.",
)
d.sensor(
    "Conflict predictor & summaries", "Random Forest + clustering · deterministic text · no generative AI",
    "Heat-signature clusters (DBSCAN) feed a Random Forest that scores conflict likelihood per cluster (the "
    "Citadel-proven pattern), with SHAP explainability on predictions. All alert summaries and Spotlight "
    "briefings are composed DETERMINISTICALLY from the alert's own numbers — no generative model anywhere in "
    "the alert path, therefore zero hallucination surface.",
    "Ranked, explainable conflict-risk alerts and plain-language briefings a commissioner can read.",
    "A risk score is a probability, not a prophecy — which is why alerts route to humans and why we publish "
    "confidence rather than certainty.",
)

# ── 4. Truth table ────────────────────────────────────────────────────────
d.section("4. THE CAPABILITY TRUTH TABLE — WHAT ORBIT CAN AND CANNOT SEE", accent=AMBER)
d.para("The table that wins expert rooms: claim exactly what the physics supports, concede the rest first.")
d.table(
    ["Land signal", "Can satellites see it?", "What our engine does"],
    [
        ["Herd animals themselves", "No — sub-pixel at 10 m, moving", "Never claimed. No honest 10 m system can."],
        ["Herd transit (trampling, 12–36 h)", "Marginal — needs a radar pass inside the window (~25% odds at 6-day revisit)",
         "Opportunistic at best; never promised."],
        ["Sustained heavy grazing (weeks, large area)", "Yes — real NDVI decline + SAR roughness change",
         "Captured, but diluted: a few hectares inside a ~900 ha averaging box shrinks toward noise. Mass dry-season movements register; one herd's night in a field does not."],
        ["Burning along movement corridors", "Strongly — FIRMS is built for this",
         "Captured daily; our most reliable herd-associated signal."],
        ["New encampments", "Yes — night-light + land-cover conversion",
         "Captured; the patent says 'encampment signature', deliberately not 'herd signature'."],
        ["Bush clearing / land conversion", "Yes — NDVI loss + SAR change + annual land-cover class flip",
         "Captured; Wayback + land-cover give the year-over-year receipt."],
        ["Harvest (the confound)", "Yes — and it looks like grazing to NDVI",
         "Acknowledged openly; crop-calendar filter is the roadmap fix. Until then, human verification separates them."],
        ["Flood water", "Yes — SAR backscatter drop, through cloud",
         "Captured at LGA scale; street-level inundation needs the future U-Net."],
        ["Drought", "Yes, but NDVI lags the moisture deficit by weeks",
         "Captured (lagging); SMAP soil-moisture percentile (feasibility proven) is the leading-indicator upgrade."],
        ["Soil pH / organic content, plant counts, crop height", "No — beyond 10 m civilian optical/radar physics",
         "Never claimed; open soil databases + ground truth are the honest route (stated to NASRDA in writing)."],
    ],
    [138, 168, 209],
)

# ── 5. Q&A armour ─────────────────────────────────────────────────────────
d.section("5. HARD QUESTIONS — APPROVED ANSWERS", accent=RED)
d.para("Encroachment is the umbrella: the platform detects abnormal land-surface disturbance consistent with "
       "encroachment pressure — grazing, clearing, burning, encampment — early enough for a field officer to "
       "verify before conflict. It does not claim to identify herds from orbit, because no honest 10-metre "
       "system can.", bold_head="“Can you see herders from space?”")
d.para("Because they reflect real uncertainty in single-location statistics. They rise two honest ways: better "
       "methodology (seasonal baselines — the 3-year history is already banked) and field verification (every "
       "confirmed detection becomes a measured precision number we will publish). A vendor showing you 95% "
       "without a verification ledger is showing you a made-up number.",
       bold_head="“Why are your confidences only 50–70%?”")
d.para("Radar (Sentinel-1) is unaffected by cloud and carries flood + disturbance detection year-round. Optical "
       "gaps are stated in-product ('latest usable pass', cloud percentage shown). We never interpolate through "
       "clouds and pretend otherwise.", bold_head="“What about clouds in the wet season?”")
d.para("Detection runs on Copernicus and NASA sensors with per-pass provenance shown in-app. Esri imagery is "
       "REFERENCE context and is labelled 'not detection-time' on the very screen it appears on.",
       bold_head="“Is the pretty imagery your detection?”")
d.para("Both, honestly labelled: LIVE rows come from the daily pipeline with model attribution; kept examples "
       "and aged-out rows are labelled HISTORICAL with dates, in grey. The provenance chips are on every card.",
       bold_head="“Is this live data or demo data?”")
d.para("Daily at 07:00 UTC the scheduler runs the full chain unattended (FIRMS → conflict → encroachment → "
       "ShockGuard), LGAs rolling on the satellite revisit; every run is stamped in an auditable runs log; "
       "external uptime monitoring measures availability continuously (SLA: 99.5%).",
       bold_head="“How fresh is it, and who runs it?”")

d.save()
print("built", OUT)
