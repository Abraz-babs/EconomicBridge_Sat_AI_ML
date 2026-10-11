"""Pre-season risk profile — the rule text, the state summary, plain sentences and the CSV.

The figures are measured by apps/ingestion/tasks/risk_profile.py and stored per
round in tenant_<id>.lga_risk_profile (JSONB `figures`). Everything a reader
sees — the page, the PDF, the CSV — is built from those rows here, so the three
can never disagree. The thresholds below are the job's; keep them in step.
"""
from __future__ import annotations

import csv
import io
from datetime import date

# Keep in step with apps/ingestion/tasks/risk_profile.py (operator-approved 2026-10-10).
RULE = {
    "flood": ("High: at least 10% of farmland in the 1-in-10-year river flood zone, or at least 5% of the LGA "
              "under water in a mapped flood. Moderate: at least 3% of farmland in the 1-in-100-year zone, or at "
              "least 1% under water. Otherwise Low. Where ESA maps less than 5% of an LGA as farmland (towns, and "
              "forest areas where farms sit under trees), the same shares of the LGA's land are used."),
    "drought": ("High: a season below 80% of normal rainfall at least 1 year in 5. Moderate: at least 1 year "
                "in 10. Otherwise Low."),
    "rains": ("High: a false start, a late onset or a long dry spell after planting at least 1 season in 3. "
              "Moderate: at least 1 season in 5. Otherwise Low."),
}
BANDS = ("high", "moderate", "low")
BAND_LABEL = {"high": "High", "moderate": "Moderate", "low": "Low", "none": "Not measured"}
BAND_ORDER = {"high": 0, "moderate": 1, "low": 2, "none": 3}
MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


# ─── numbers ──────────────────────────────────────────────────────────────

def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank agreement of two lists (1 = same order). None when either is constant."""
    if len(a) < 3 or len(a) != len(b):
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if not va or not vb:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (va * vb) ** 0.5, 2)


def summarise(rows: list[dict]) -> dict:
    """State figures from the per-LGA rows (dicts with band_* and figures)."""
    figs = [r["figures"] for r in rows]
    bands = {k: {b: sum(1 for r in rows if r[f"band_{k}"] == b) for b in (*BANDS, "none")}
             for k in ("flood", "drought", "rains")}
    keys: list[tuple[str, str]] = []
    for f in figs:
        for k, m in (f.get("flood", {}).get("mapped") or {}).items():
            if (k, m.get("label", k)) not in keys:
                keys.append((k, m.get("label", k)))
    zone = [(f.get("flood") or {}).get("rp10_crop_pct") or 0.0 for f in figs]
    mapped = []
    for k, label in keys:
        seen = [((f.get("flood") or {}).get("mapped") or {}).get(k) or {} for f in figs]
        mapped.append({
            "key": k, "label": label,
            "cropland_ha": int(sum(s.get("crop_ha") or 0 for s in seen)),
            "lgas_with_water": sum(1 for s in seen if (s.get("area_pct") or 0) >= 1),
            "agreement": spearman(zone, [s.get("area_pct") or 0.0 for s in seen]),
        })
    drought = [len((f.get("rain") or {}).get("drought_seasons") or []) for f in figs]
    rains = [f.get("rains") for f in figs if f.get("rains") and f["rains"].get("years")]
    failed = [len(r.get("failed_seasons") or []) for r in rains]
    rain0 = next((f.get("rain") for f in figs if f.get("rain")), {}) or {}
    people = [((f.get("exposure") or {}).get("people")) for f in figs]
    return {
        "lgas": len(rows),
        "cropland_ha": int(sum(f.get("cropland_ha") or 0 for f in figs)),
        "rp10_cropland_ha": int(sum((f.get("flood") or {}).get("rp10_crop_ha") or 0 for f in figs)),
        "rp100_cropland_ha": int(sum((f.get("flood") or {}).get("rp100_crop_ha") or 0 for f in figs)),
        "mapped": mapped,
        "bands": bands,
        "seasons": (rain0.get("last_year", 0) - rain0.get("first_year", 0) + 1) if rain0 else 0,
        "drought_seasons_min": min(drought) if drought else None,
        "drought_seasons_max": max(drought) if drought else None,
        "rains_seasons": max((len(r["years"]) for r in rains), default=None),
        "rains_failed_min": min(failed) if failed else None,
        "rains_failed_max": max(failed) if failed else None,
        "people": int(sum(p for p in people if p)) if any(people) else None,
    }


# ─── words ────────────────────────────────────────────────────────────────

def zone_share(fl: dict) -> str:
    """The 1-in-10-year figure as the band reads it: of farmland, or of land."""
    if fl.get("basis") == "land":
        return f"{pc(fl.get('rp10_area_pct'))} of land"
    return f"{pc(fl.get('rp10_crop_pct'))} of farmland · {ha(fl.get('rp10_crop_ha'))}"


def ha(v: float | None) -> str:
    if v is None:
        return "—"
    v = round(v / 100) * 100 if v >= 1000 else round(v)
    return f"{int(v):,} ha"


def pc(v: float | None, nd: int = 1) -> str:
    if v is None:
        return "—"
    if 0 < v < 10 ** -nd:
        return f"<{10 ** -nd:g}%"
    return f"{v:.{nd}f}%"


def onset_text(mmdd: str | None) -> str | None:
    if not mmdd:
        return None
    m, d = (int(x) for x in mmdd.split("-"))
    return f"{d} {MONTHS[m]}"


def season_span(months: list[int]) -> str:
    return f"{MONTHS[months[0]][:3]}–{MONTHS[months[-1]][:3]}" if months else "—"


def plain_sentences(lga: str, f: dict) -> list[str]:
    """What the figures say about one LGA, in plain words (page and PDF)."""
    out = []
    fl = f.get("flood") or {}
    if fl.get("basis") == "land":
        za, za100 = fl.get("rp10_area_pct") or 0.0, fl.get("rp100_area_pct") or 0.0
        lead = (f"ESA maps little farmland in {lga} ({pc(f.get('cropland_pct'))} of the LGA; farms under trees read "
                "as tree cover), so its flood band reads its land: ")
        if za >= 10:
            out.append(lead + f"{round(za)}% of it lies in the zone the river model floods about once every 10 years.")
        elif za100 >= 3:
            out.append(lead + f"{round(za100)}% lies in the 1-in-100-year zone and {pc(za)} in the 1-in-10-year zone.")
        else:
            out.append(lead + f"almost none lies in the modelled river flood zones ({pc(za100)} in the 1-in-100-year zone).")
    else:
        z, z100 = fl.get("rp10_crop_pct") or 0.0, fl.get("rp100_crop_pct") or 0.0
        if z >= 10:
            out.append(f"{round(z)}% of {lga}'s farmland ({ha(fl.get('rp10_crop_ha'))}) lies in the zone the river "
                       "model floods about once every 10 years.")
        elif z100 >= 3:
            out.append(f"{round(z100)}% of {lga}'s farmland lies in the 1-in-100-year river flood zone, and "
                       f"{pc(z)} in the 1-in-10-year zone.")
        else:
            out.append(f"Almost none of {lga}'s farmland lies in the modelled river flood zones "
                       f"({pc(z100)} in the 1-in-100-year zone).")
    maps = list((fl.get("mapped") or {}).values())
    seen = [m for m in maps if (m.get("area_pct") or 0) >= 1]
    if seen:
        out.append("Satellites saw flood water over " + " and ".join(
            f"{pc(m['area_pct'])} of the LGA on {m['label']}" for m in seen) + ".")
    elif maps:
        out.append(("Neither" if len(maps) == 2 else "No") + " mapped flood put as much as 1% of the LGA under water.")
    r = f.get("rain") or {}
    k = len(r.get("drought_seasons") or [])
    n = (r.get("last_year", 0) - r.get("first_year", 0) + 1) if r else 0
    w = r.get("worst") or {}
    if n:
        lead = f"{k} of the {n} seasons since {r['first_year']} fell" if k else f"No season since {r['first_year']} fell"
        out.append(f"{lead} below 80% of normal rainfall; the driest was {w.get('year')} at "
                   f"{round(w.get('pct_of_normal') or 0)}% of normal.")
    rains = f.get("rains") or {}
    if rains.get("years"):
        ny = len(rains["years"])
        fails = len(rains.get("failed_seasons") or [])
        parts = [f"{len(rains.get('false_starts') or [])} false starts",
                 f"{len(rains.get('late_onsets') or [])} late onsets",
                 f"{len(rains.get('long_dry_spells') or [])} long dry spells after planting"]
        on = onset_text(rains.get("onset_median"))
        out.append(f"Since {rains['years'][0]}, {fails} of {ny} seasons had a false start, a late onset or a long "
                   f"dry spell ({', '.join(parts)})" + (f"; the rains usually set in around {on}." if on else "."))
    return out


# ─── CSV ──────────────────────────────────────────────────────────────────

def csv_text(rows: list[dict], through: int, method: str) -> str:
    keys: list[str] = []
    for r in rows:
        for k in ((r["figures"].get("flood") or {}).get("mapped") or {}):
            if k not in keys:
                keys.append(k)
    head = ["lga", "band_flood", "band_drought", "band_failed_rains", "flood_basis", "cropland_ha", "cropland_pct",
            "farmland_in_1in10_zone_pct", "farmland_in_1in10_zone_ha", "farmland_in_1in100_zone_pct",
            "farmland_in_1in100_zone_ha", "farmland_deeper_than_1m_1in100_pct", "land_in_1in10_zone_pct",
            "land_in_1in100_zone_pct"]
    for k in keys:
        head += [f"water_{k}_lga_pct", f"water_{k}_farmland_ha", f"cloud_{k}_lga_pct"]
    head += ["season_months", "normal_season_mm", "year_to_year_swing_pct", "seasons_below_80pct",
             "seasons_below_80pct_years", "driest_season", "driest_pct_of_normal", "daily_seasons",
             "usual_onset", "false_start_years", "late_onset_years", "long_dry_spell_years", "failed_rain_seasons",
             "villages", "people", "under5", "through_season", "method", "sources"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    for r in sorted(rows, key=lambda x: x["lga"]):
        f = r["figures"]
        fl = f.get("flood") or {}
        rain = f.get("rain") or {}
        rains = f.get("rains") or {}
        ex = f.get("exposure") or {}
        line = [r["lga"], r["band_flood"], r["band_drought"], r["band_rains"], fl.get("basis", "farmland"),
                f.get("cropland_ha"), f.get("cropland_pct"), fl.get("rp10_crop_pct"), fl.get("rp10_crop_ha"),
                fl.get("rp100_crop_pct"), fl.get("rp100_crop_ha"), fl.get("rp100_deep_crop_pct"),
                fl.get("rp10_area_pct"), fl.get("rp100_area_pct")]
        for k in keys:
            m = (fl.get("mapped") or {}).get(k) or {}
            line += [m.get("area_pct"), m.get("crop_ha"), m.get("cloud_pct")]
        line += [" ".join(MONTHS[m][:3] for m in rain.get("season_months") or []), rain.get("normal_mm"),
                 rain.get("cv_pct"), len(rain.get("drought_seasons") or []),
                 " ".join(str(y) for y in rain.get("drought_seasons") or []),
                 (rain.get("worst") or {}).get("year"), (rain.get("worst") or {}).get("pct_of_normal"),
                 len(rains.get("years") or []) or None, onset_text(rains.get("onset_median")),
                 " ".join(str(y) for y in rains.get("false_starts") or []),
                 " ".join(str(y) for y in rains.get("late_onsets") or []),
                 " ".join(str(y) for y in rains.get("long_dry_spells") or []),
                 len(rains.get("failed_seasons") or []) if rains.get("years") else None,
                 ex.get("villages"), ex.get("people"), ex.get("under5"), through, method, r.get("sources")]
        w.writerow(["" if v is None else v for v in line])
    return buf.getvalue()


def filename(tenant: str, through: int, ext: str) -> str:
    return f"risk_profile_{tenant}_through_{through}_{date.today().isoformat()}.{ext}"
