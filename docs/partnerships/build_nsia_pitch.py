"""Generate the NSIA Demo Day pitch materials:
  1. EconomicBridge_NSIA_DemoDay_Script.pdf  — full script + Q&A war-room
  2. EconomicBridge_NSIA_CueCard.pdf          — one-page stage cue card

    apps/api/.venv/Scripts/python.exe docs/partnerships/build_nsia_pitch.py
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image,
)

DL = Path(r"C:\Users\HP\Downloads")
LOGO = Path(r"C:\Users\HP\Downloads\Company Logo.jpg")

GREEN = colors.HexColor("#1f8a3b")
DGREEN = colors.HexColor("#0a5c2e")
INK = colors.HexColor("#15201a")
MUTED = colors.HexColor("#5b6b60")
QUOTE_BG = colors.HexColor("#eef7f0")
DEMO_BG = colors.HexColor("#0a5c2e")
CARD_ALT = colors.HexColor("#f0f7f2")

BODY, BODY_B, BODY_I = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
try:
    pdfmetrics.registerFont(TTFont("EB", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("EBB", r"C:\Windows\Fonts\arialbd.ttf"))
    pdfmetrics.registerFont(TTFont("EBI", r"C:\Windows\Fonts\ariali.ttf"))
    pdfmetrics.registerFont(TTFont("EBBI", r"C:\Windows\Fonts\arialbi.ttf"))
    pdfmetrics.registerFontFamily("EB", normal="EB", bold="EBB", italic="EBI", boldItalic="EBBI")
    BODY, BODY_B, BODY_I = "EB", "EBB", "EBI"
except Exception:  # noqa: BLE001
    pass


def S(name, **kw):
    base = dict(fontName=BODY, fontSize=10.5, leading=14.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


def logo_flow(width_mm):
    if not LOGO.exists():
        return Spacer(1, 1)
    img = Image(str(LOGO))
    img.drawHeight = width_mm * mm * img.drawHeight / img.drawWidth
    img.drawWidth = width_mm * mm
    img.hAlign = "LEFT"
    return img


# ═══════════════════════════ 1. FULL SCRIPT ════════════════════════════════
def build_script():
    out = DL / "EconomicBridge_NSIA_DemoDay_Script.pdf"
    title = S("t", fontName=BODY_B, fontSize=19, leading=23, textColor=DGREEN)
    meta = S("m", fontSize=9.5, textColor=MUTED, spaceAfter=2)
    beat = S("b", fontName=BODY_B, fontSize=12.5, leading=16, textColor=DGREEN,
             spaceBefore=9, spaceAfter=3)
    note = S("n", fontName=BODY_I, fontSize=9, leading=12, textColor=MUTED, spaceAfter=3)
    step = S("s", fontSize=10, leading=13.5, leftIndent=12, spaceAfter=2)
    qa_q = S("qq", fontName=BODY_B, fontSize=10.5, leading=14, textColor=INK, spaceBefore=6)
    qa_a = S("qa", fontSize=10, leading=13.5, leftIndent=12, spaceAfter=2)
    tip = S("tip", fontSize=10, leading=13.5, leftIndent=12, spaceAfter=3)
    say = S("say", fontSize=11, leading=15.5, textColor=INK)

    def quote(text):
        p = Paragraph(text, say)
        t = Table([[p]], colWidths=[165 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
            ("LINEBEFORE", (0, 0), (0, -1), 2.2, GREEN),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    def beat_hd(time, name):
        return Paragraph(f'<font color="#1f8a3b">{time}</font>&nbsp;&nbsp;{name}', beat)

    st = [
        logo_flow(16), Spacer(1, 3),
        Paragraph("EconomicBridge — NSIA Demo Day Script", title),
        Paragraph("Abdullahi Zuru Ibrahim, Founder &amp; CEO · Bizra Farms Integrated Nigeria Ltd · "
                  "~5-minute pitch + live demo + Q&amp;A", meta),
        Paragraph("Golden rule: every claim here is true and shown live. Judges fund evidence, not adjectives. "
                  "Learn the beats — don't read this on stage.", meta),
        HRFlowable(width="100%", thickness=1, color=GREEN, spaceBefore=5, spaceAfter=3),

        beat_hd("0:00", "THE OPEN — the hook"),
        Paragraph("Stand still. Slow. Look at the judges, not the screen.", note),
        quote("&ldquo;Judges — last rainy season, a farmer in Nigeria's middle belt woke up to find a full year of "
              "work gone. His entire field, trampled overnight by cattle that crossed his boundary while he slept. "
              "He had no warning. His state government learned about it days later — from the body count that "
              "followed.<br/><br/>That story repeats <b>thousands of times a year</b>. It's the difference between "
              "a family that eats and a family that doesn't.<br/><br/>Here's what almost no one realizes: <b>the "
              "satellite that could have warned him was already overhead.</b> The data existed. Nobody was reading "
              "it.<br/><br/>We are. My name is Abdullahi Zuru Ibrahim, and this is <b>EconomicBridge.</b>&rdquo;"),

        beat_hd("0:35", "THE PROBLEM"),
        quote("&ldquo;Across Nigeria, the biggest decisions in food security, farmland conflict and disaster "
              "response are made <b>blind</b> — on field reports that arrive days late, and census maps that are "
              "years out of date. The commercial fix costs a fortune: foreign satellite platforms charge a single "
              "ministry <b>hundreds of thousands of dollars a year</b>, for one problem at a time. No Nigerian "
              "state can afford to see.&rdquo;"),

        beat_hd("1:00", "THE INSIGHT"),
        quote("&ldquo;So we asked a different question. <b>What if you didn't need to buy the imagery at all?</b> "
              "Europe's Copernicus and America's NASA fly over Nigeria every few days and give the data away — free "
              "and open. The problem was never the data. It was that no one built the intelligence layer to turn it "
              "into decisions <b>at the level a Nigerian official actually works: the Local Government Area.</b> "
              "That's what we built. And it's live right now — let me show you.&rdquo;"),

        beat_hd("1:25", "LIVE DEMO — the differentiator"),
        Paragraph("Switch to browser (economicbridge.org already on the dashboard). Narrate while you click — "
                  "never go silent.", note),
        Paragraph("<b>1. Farmland map</b> (open first — the pulsing halos):", step),
        quote("&ldquo;Real satellite intelligence over our pilot states, right now. Every marker is a <b>live "
              "farmland encroachment watch</b> — 149 of them — from fused radar and optical passes, per Local "
              "Government Area. Not a mock-up.&rdquo;"),
        Paragraph("<b>2. CropGuard — statewide crop health</b> (switch module):", step),
        quote("&ldquo;Same platform, different decision. The crop health of <b>every Local Government Area — all "
              "447</b> across our pilot tenants — read from Sentinel-2. Green healthy, red stressed. A commissioner "
              "sees his whole state's food supply in one glance.&rdquo;"),
        Paragraph("<b>3. Leaf-photo diagnosis</b> (upload a leaf, or show a prior result):", step),
        quote("&ldquo;At the farmer's level — a farmer photographs a sick plant, and our AI model, which we trained "
              "ourselves to <b>87% accuracy across twelve crop diseases</b>, tells them what it is and what to "
              "do.&rdquo;"),
        Paragraph("<b>4. Provenance panel</b> (open it — the trust close):", step),
        quote("&ldquo;Because a government must trust what it acts on — every indicator traces back to its exact "
              "satellite source and open licence. <b>Nothing here is a black box. Nothing here is invented.</b>&rdquo;"),

        beat_hd("2:55", "WHY IT'S REAL"),
        quote("&ldquo;Most of what you'll see today is a promise of what could be built. <b>EconomicBridge is "
              "already built.</b> Live, secure, on cloud infrastructure, across seven decision areas — and it "
              "already sends <b>automated early-warning alerts straight to the responsible agencies</b> in plain "
              "English.&rdquo;"),

        beat_hd("3:20", "THE BUSINESS"),
        quote("&ldquo;And it pays for itself. Because our data is free, our cost to add another state barely moves "
              "— so we sell whole-government intelligence at a fraction of the foreign price. <b>A state starts at "
              "$15,000 a year. A federal agency, $60,000. A nationwide federal deployment, up to $300,000.</b> We "
              "go to market through partnership — in active discussions with <b>NASRDA</b>, and invited into the "
              "<b>World Food Programme's</b> innovation pipeline. The same platform scales across all 15 ECOWAS "
              "states.&rdquo;"),

        beat_hd("3:55", "THE ASK &amp; VISION"),
        quote("&ldquo;We didn't come for seed money to go <i>build</i> something. It's built, it's working, and "
              "it's ready to become <b>national infrastructure.</b> With NSIA behind us, in twelve months "
              "EconomicBridge covers all 774 Local Government Areas, delivers alerts in Hausa, Yoruba, Igbo and "
              "Fulfulde to farmers on basic phones, and becomes the sovereign eyes this country has never had over "
              "its own land. Nigeria's food security, decided with Nigerian intelligence, owned in Nigeria.&rdquo;"),

        beat_hd("4:30", "THE CLOSE"),
        Paragraph("Slow down. This is the line they remember in the judging room.", note),
        quote("&ldquo;That farmer didn't lose his field because the warning was impossible. He lost it because "
              "<b>no one was looking.</b><br/><br/>EconomicBridge is Nigeria, finally looking. Thank you.&rdquo;"),
        Paragraph("Stop. Don't fill the silence. Let them come to you.", note),

        HRFlowable(width="100%", thickness=1, color=GREEN, spaceBefore=10, spaceAfter=3),
        beat_hd("", "3-MINUTE COMPRESSION (if they cut the time)"),
        Paragraph("Open (farmer hook, 20s) &rarr; &ldquo;the satellite was already overhead, no one was reading it "
                  "— we are&rdquo; (15s) &rarr; <b>live demo: Farmland + CropGuard 447 LGAs + provenance</b> (60s) "
                  "&rarr; &ldquo;already built, live, 7 modules, alerts to agencies today&rdquo; (20s) &rarr; "
                  "&ldquo;free data, we undercut foreign vendors — $15k state to $300k federal, via NASRDA + "
                  "WFP&rdquo; (25s) &rarr; &ldquo;NSIA takes us to all 774 LGAs — sovereign eyes on our own "
                  "land&rdquo; (20s) &rarr; close (farmer line, 15s).", step),

        HRFlowable(width="100%", thickness=1, color=GREEN, spaceBefore=10, spaceAfter=3),
        beat_hd("", "Q&amp;A WAR-ROOM — rehearse these; it's won here"),
    ]

    qa = [
        ("&ldquo;How is this different from foreign EO vendors?&rdquo;",
         "&ldquo;They sell one expensive tool per ministry on paid imagery. We sell seven decision areas to a "
         "whole government on <i>free</i> imagery, per-LGA, with Nigerian data sovereignty and local-language "
         "farmer alerts they don't offer — at 30 to 70% less.&rdquo;"),
        ("&ldquo;Does it actually work — your accuracy?&rdquo;",
         "&ldquo;Our crop-disease model is genuinely trained and validated at 87%. Our satellite indicators are "
         "corroborated across multiple independent sensors to suppress false alarms — all auditable in the "
         "provenance panel. We'd rather show a real 87% than claim a fake 99.&rdquo; "
         "(Never invent a conflict-prediction number — say &lsquo;validated per deployment against ground-truth "
         "records.&rsquo;)"),
        ("&ldquo;What's your traction / revenue?&rdquo;",
         "&ldquo;The product is live and covers 447 LGAs today; we've issued beta access to seven states and FCT "
         "and are converting those to paid licences, with NASRDA as the anchor channel. We're pre-revenue by "
         "choice — we built the capability first, so the sale is a demo, not a promise.&rdquo;"),
        ("&ldquo;Can it scale — what's the moat?&rdquo;",
         "&ldquo;A new state is a configuration change, not a rebuild — schema-isolated multi-tenancy. The moat is "
         "the per-LGA baseline we accumulate every satellite pass, our locally-trained models, and government "
         "relationships. The data advantage compounds daily.&rdquo;"),
        ("&ldquo;Team — can one founder do this?&rdquo;",
         "&ldquo;Bizra Farms is a registered agribusiness with two directors — myself and our CFO — and real "
         "working farms. Built by people who <i>farm</i>, for decisions that reach farmers. I built and operate "
         "the whole stack; the CFO runs the business.&rdquo;"),
        ("&ldquo;Why should NSIA invest / use of funds?&rdquo;",
         "&ldquo;Three-quarters to scaling to all 774 LGAs and the next models; the rest to farmer SMS reach and "
         "compliance. And NSIA on our cap table isn't just capital — it's the credibility that opens every federal "
         "door we're already knocking on.&rdquo;"),
        ("&ldquo;Is the data really free to commercialize?&rdquo;",
         "&ldquo;Yes — Copernicus and NASA data are open-licence and cleared for commercial use with attribution, "
         "which we display. That's the foundation of our cost advantage, and it's legally solid.&rdquo;"),
    ]
    for q, a in qa:
        st.append(Paragraph(q, qa_q))
        st.append(Paragraph(a, qa_a))

    st += [
        HRFlowable(width="100%", thickness=1, color=GREEN, spaceBefore=10, spaceAfter=3),
        beat_hd("", "DELIVERY TIPS"),
        Paragraph("&bull;&nbsp;&nbsp;Rehearse the demo click-path 20 times; keep a <b>screenshot fallback</b> ready "
                  "in case venue wifi dies — talk over stills without missing a beat. Top up AWS credits so the "
                  "live site is definitely up on the day.", tip),
        Paragraph("&bull;&nbsp;&nbsp;In the live demo, stay on the maps, leaf-diagnosis and provenance — <b>don't "
                  "open the System Status panel</b> (cosmetic, not yet wired to live telemetry).", tip),
        Paragraph("&bull;&nbsp;&nbsp;Don't read this on stage. Learn the beats; speak to the judges. The farmer "
                  "opens and closes it — everything between is you being calm and certain about a thing that "
                  "already works.", tip),
        Paragraph("&bull;&nbsp;&nbsp;End on time and stop talking. Confidence is silence after the close.", tip),
    ]

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=15 * mm, bottomMargin=14 * mm,
                      title="EconomicBridge — NSIA Demo Day Script",
                      author="Bizra Farms Integrated Nigeria Ltd").build(st)
    print("built", out.name)


# ═══════════════════════════ 2. CUE CARD (1 page) ══════════════════════════
def build_cuecard():
    out = DL / "EconomicBridge_NSIA_CueCard.pdf"
    cell_t = S("ct", fontName=BODY_B, fontSize=11, textColor=DGREEN)
    cell_b = S("cb", fontName=BODY_B, fontSize=10.5, textColor=INK)
    cell_x = S("cx", fontSize=9.8, leading=12.5, textColor=INK)
    demo_t = S("dt", fontName=BODY_B, fontSize=10.5, textColor=colors.white)
    demo_x = S("dx", fontSize=9.8, leading=13, textColor=colors.white)
    call_l = S("cl", fontName=BODY_B, fontSize=9.5, textColor=GREEN)
    call_x = S("clx", fontSize=11, leading=15, textColor=INK)
    foot = S("f", fontSize=9, leading=12, textColor=MUTED)
    title = S("t", fontName=BODY_B, fontSize=16, leading=18, textColor=DGREEN)
    sub = S("s", fontSize=9, textColor=MUTED)

    def callout(label, text, bg):
        inner = [[Paragraph(label, call_l)], [Paragraph(text, call_x)]]
        t = Table(inner, colWidths=[181 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, GREEN),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (0, 0), 4), ("BOTTOMPADDING", (0, 0), (0, 0), 0),
            ("TOPPADDING", (0, 1), (0, 1), 1), ("BOTTOMPADDING", (0, 1), (0, 1), 5),
        ]))
        return t

    rows = [
        ["TIME", "BEAT", "SAY / DO"],
        ["0:35", "PROBLEM",
         "Decisions made <b>BLIND</b> — field reports days late, census years old. Foreign EO = <b>$100k+</b> per ministry, one problem at a time."],
        ["1:00", "INSIGHT",
         "<b>Don't buy imagery — it's free.</b> Copernicus + NASA fly over us. No one built the intelligence layer at <b>LGA level</b>. We did. &ldquo;It's live — let me show you.&rdquo;"],
        ["1:25", "DEMO", "__DEMO__"],
        ["2:55", "IT'S REAL",
         "Not a promise — <b>already built.</b> Live, secure, 7 modules, <b>auto-alerts to agencies</b> (NEMA) today."],
        ["3:20", "BUSINESS",
         "Free data &rarr; we undercut. <b>$15k state · $60k agency · $300k federal.</b> Channel: <b>NASRDA</b> + <b>WFP</b>. Scales to 15 ECOWAS states."],
        ["3:55", "ASK",
         "Not seed money to build — it's built. <b>NSIA &rarr; all 774 LGAs</b>, farmer SMS in 4 languages, sovereign eyes on our own land."],
    ]

    data = []
    for r in rows:
        if r[0] == "TIME":
            data.append([Paragraph("TIME", demo_t), Paragraph("BEAT", demo_t),
                         Paragraph("SAY / DO", demo_t)])
        elif r[2] == "__DEMO__":
            demo = ("<b>1</b> Farmland map — 149 live encroachment watches, per-LGA &nbsp;|&nbsp; "
                    "<b>2</b> CropGuard — all 447 LGAs crop health &nbsp;|&nbsp; "
                    "<b>3</b> Leaf photo &rarr; AI 87% &nbsp;|&nbsp; "
                    "<b>4</b> Provenance — &ldquo;nothing invented&rdquo;")
            data.append([Paragraph("1:25", demo_t), Paragraph("LIVE DEMO", demo_t), Paragraph(demo, demo_x)])
        else:
            data.append([Paragraph(r[0], cell_b), Paragraph(r[1], cell_t), Paragraph(r[2], cell_x)])

    tbl = Table(data, colWidths=[15 * mm, 27 * mm, 139 * mm])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DGREEN),
        ("BACKGROUND", (0, 3), (-1, 3), DEMO_BG),   # demo row
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d8cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in (2, 4, 6):   # zebra on non-demo body rows
        style.append(("BACKGROUND", (0, i), (-1, i), CARD_ALT))
    tbl.setStyle(TableStyle(style))

    header = Table([[logo_flow(13),
                     Paragraph("NSIA DEMO DAY — STAGE CUE CARD", title)]],
                   colWidths=[20 * mm, 161 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (0, 0), 0)]))

    st = [
        header,
        Paragraph("EconomicBridge · ~5 min + demo · learn the beats, speak to the judges", sub),
        Spacer(1, 6),
        callout("0:00  OPEN  (slow, still, eyes on judges)",
                "&ldquo;A farmer woke to find a year's work gone — his field trampled overnight, no warning. "
                "His government learned days later, from the body count. <b>The satellite that could have warned "
                "him was already overhead. Nobody was reading it. We are.</b> I'm Abdullahi Zuru Ibrahim — this is "
                "EconomicBridge.&rdquo;", QUOTE_BG),
        Spacer(1, 6),
        tbl,
        Spacer(1, 6),
        callout("4:30  CLOSE  (slow — the line they remember — then STOP)",
                "&ldquo;That farmer didn't lose his field because the warning was impossible. He lost it because "
                "<b>no one was looking.</b> EconomicBridge is Nigeria, finally looking. Thank you.&rdquo;", QUOTE_BG),
        Spacer(1, 7),
        HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4),
        Paragraph("<b>REMEMBER:</b> &nbsp;Don't read this — speak to them. &nbsp;·&nbsp; Screenshot fallback ready "
                  "(wifi). &nbsp;·&nbsp; Skip the System Status panel. &nbsp;·&nbsp; Never invent a conflict-accuracy "
                  "number. &nbsp;·&nbsp; End on time, then <b>silence.</b>", foot),
    ]

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                      topMargin=13 * mm, bottomMargin=12 * mm,
                      title="EconomicBridge — NSIA Cue Card",
                      author="Bizra Farms Integrated Nigeria Ltd").build(st)
    print("built", out.name)


if __name__ == "__main__":
    build_script()
    build_cuecard()
    print("done")
