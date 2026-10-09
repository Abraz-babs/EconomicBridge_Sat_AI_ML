"""Claim check — what the satellites show on one plot around a LOSS DATE.

Farm Check reads the latest pass. An insurer asks a different question: for a
loss reported on date D at coordinates X, what do the satellites show before
and after D? This module answers that for a flood, drought or general claim by
comparing a window BEFORE the loss with a window AFTER it:

  * radar (Sentinel-1) — the share of the plot reading as open water;
  * optical (Sentinel-2) — vegetation (NDVI) before and after.

It produces EVIDENCE with its thresholds and every pass it used, never a claim
decision. Three honesty rules are built in, because each failure here would be
silent and would land on a real farmer or a real insurer:

  1. "Not supported" is never "rejected": the verdict wording only ever says
     what the satellite saw, and recommends a field check when it saw nothing.
  2. Radar open-water flagging misses flooded VEGETATION (reeds, tall crop):
     water under a canopy can look bright, not dark. A "no water signal" is
     therefore not proof of no flood, and the result says so.
  3. NDVI also falls with harvest and natural maturity, so a vegetation
     decline alone is not proof of loss.

The windows, thresholds and passes are returned so a result can be re-run and
challenged. Measured on the 2024 Kebbi floods, local methods missed the
flooded areas entirely (0 of 11); this check has NOT been validated against
loss records and is described as indicative until it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median

from sources.farm_check import (
    DEFAULT_HALF_M,
    FARM_RESOLUTION_DEG,
    bbox_around,
    normalise_crop,
)
from sources.sentinel_statistical import (
    EVALSCRIPT_S2_NDVI_CLOUDMASKED,
    SentinelStatisticalClient,
    StatPoint,
    evalscript_s1_water,
)

SOURCE = "copernicus_sentinel_claim_v1"

# Windows, in days relative to the loss date D.
#   before = D-60 .. D-15   the plot's normal state
#   event  = D-14 .. D+30   when the loss could have happened
# The event window opens 14 days BEFORE the reported date because floods build
# up over days and losses are often reported after the water has arrived. With
# a 2-day gap, a plot found 74% under water on D-6 (Kebbi, 1 Sep 2024) counted
# as "before" and the flood was graded only partial.
BASELINE_DAYS = 60
EVENT_LEAD_DAYS = 14
AFTER_DAYS = 30          # the event window runs this far past the loss date
MIN_AGE_AFTER_DAYS = 6   # Sentinel-1 revisits every ~6-12 days: too early to judge
EARLIEST_LOSS = date(2017, 1, 1)   # both Sentinel archives are dense from here

# Radar open water: VV backscatter below this reads as calm open water.
WATER_DB = -17.0
FLOOD_STRONG_AFTER = 0.40    # share of the plot reading as water after the loss
FLOOD_STRONG_RISE = 0.30     # ... and at least this much more than before
FLOOD_PARTIAL_AFTER = 0.15
FLOOD_PARTIAL_RISE = 0.10
ALREADY_WET_BEFORE = 0.30    # water was already there before: cannot attribute

# Vegetation.
BARE_BEFORE_NDVI = 0.20      # almost no vegetation before: nothing to lose
NDVI_MARKED_ABS, NDVI_MARKED_REL = 0.15, 0.30
NDVI_MODERATE_ABS, NDVI_MODERATE_REL = 0.08, 0.15
MIN_VALID_FRACTION = 0.25    # a pass must have this much of the plot unmasked

PERILS = ("flood", "drought", "general")


@dataclass(slots=True)
class ClaimResult:
    """Everything returned to the caller; also what the report prints."""

    lat: float
    lon: float
    loss_date: str
    peril: str
    crop: str
    area_ha: float
    windows: dict[str, str]
    thresholds: dict[str, float]
    ndvi_passes: list[dict] = field(default_factory=list)
    water_passes: list[dict] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    flood_evidence: str = "insufficient"
    vegetation_change: str = "insufficient"
    conclusion: str = "inconclusive"
    summary: str = ""
    recommendation: str = ""
    limitations: list[str] = field(default_factory=list)
    source: str = SOURCE


# ─── Pure logic (unit-tested; no network) ─────────────────────────────────


def split_windows(loss: date) -> dict[str, tuple[date, date]]:
    """The before and event ("after") windows, as inclusive (start, end) dates."""
    return {
        "before": (loss - timedelta(days=BASELINE_DAYS), loss - timedelta(days=EVENT_LEAD_DAYS + 1)),
        "after": (loss - timedelta(days=EVENT_LEAD_DAYS), loss + timedelta(days=AFTER_DAYS)),
    }


def _in(d: date, window: tuple[date, date]) -> bool:
    return window[0] <= d <= window[1]


def usable_optical(points: list[StatPoint]) -> list[StatPoint]:
    """Optical passes with a real reading over enough of the plot. The valid
    fraction is measured against the plot, not against the clearest pass, so a
    pass that sees a sliver of the plot cannot masquerade as a reading."""
    return [p for p in points
            if p.mean is not None and p.valid_fraction >= MIN_VALID_FRACTION]


def classify_flood(before: list[float], after: list[float]) -> tuple[str, float | None, float | None]:
    """(evidence, water_before, water_after_peak) from radar open-water shares.

    evidence: strong | partial | none | indeterminate | insufficient
    """
    if not after:
        return "insufficient", None, None
    peak = max(after)
    base = median(before) if before else None
    if base is not None and base >= ALREADY_WET_BEFORE:
        # Paddy, wetland, seasonal pond: water before the loss cannot be
        # attributed to the loss from radar alone.
        return "indeterminate", base, peak
    rise = peak - (base if base is not None else 0.0)
    if peak >= FLOOD_STRONG_AFTER and rise >= FLOOD_STRONG_RISE:
        return "strong", base, peak
    if peak >= FLOOD_PARTIAL_AFTER and rise >= FLOOD_PARTIAL_RISE:
        return "partial", base, peak
    return "none", base, peak


def persistent_low(after: list[float]) -> float:
    """The level vegetation stayed down at after the loss: the SECOND-lowest
    pass when there are three or more. A lost crop stays low; a single dip
    that recovers on the next pass is haze or thin cloud the mask missed
    (Kogi, 4 Oct 2022: 0.42 between 0.72 and 0.63 graded a dry control plot
    'marked decline' when the single lowest pass was used)."""
    ordered = sorted(after)
    return ordered[1] if len(ordered) >= 3 else ordered[0]


def classify_vegetation(before: list[float], after: list[float]) -> tuple[str, float | None, float | None]:
    """(change, ndvi_before, ndvi_after_low): marked | moderate | none |
    not_assessable | insufficient."""
    if not before or not after:
        return "insufficient", (median(before) if before else None), (persistent_low(after) if after else None)
    base = median(before)
    low = persistent_low(after)
    if base < BARE_BEFORE_NDVI:
        return "not_assessable", base, low
    drop = base - low
    rel = drop / base if base > 0 else 0.0
    if drop >= NDVI_MARKED_ABS and rel >= NDVI_MARKED_REL:
        return "marked", base, low
    if drop >= NDVI_MODERATE_ABS and rel >= NDVI_MODERATE_REL:
        return "moderate", base, low
    return "none", base, low


def conclude(peril: str, flood: str, veg: str) -> tuple[str, str, str]:
    """(conclusion, summary, recommendation). Wording only ever states what the
    satellite saw; a lack of evidence recommends a field check, never rejection."""
    if peril == "flood":
        if flood == "strong":
            return ("supports",
                    "Radar shows open water over a large share of the plot after the loss date that was not there before.",
                    "Satellite evidence is consistent with a flood. Normal claim handling applies.")
        if flood == "partial" or (flood in ("none", "indeterminate") and veg == "marked"):
            return ("partly_supports",
                    "The satellite evidence is partial: "
                    + ("some open water appears after the loss date" if flood == "partial"
                       else "no open-water signal, but vegetation fell sharply after the loss date")
                    + ".",
                    "Evidence is not conclusive either way. A field visit is recommended.")
        if flood == "indeterminate":
            return ("inconclusive",
                    "Water was already present on the plot before the loss date, so radar cannot separate the loss from it.",
                    "Radar cannot decide this claim. A field visit is recommended.")
        if flood == "none":
            return ("not_supported",
                    "No open-water signal and no marked vegetation decline were seen on the plot after the loss date.",
                    "The satellites did not see the reported flood. This is not proof that it did not happen: flooded "
                    "vegetation can be missed. A field visit is recommended before any decision.")
        return ("inconclusive",
                "No usable radar pass was available after the loss date.",
                "No satellite evidence either way. A field visit is recommended.")
    # drought / general: vegetation only
    if veg == "marked":
        return ("supports", "Vegetation fell sharply after the loss date.",
                "Satellite evidence is consistent with crop loss. Harvest and natural maturity can also lower NDVI, so "
                "check the reported growth stage.")
    if veg == "moderate":
        return ("partly_supports", "Vegetation fell moderately after the loss date.",
                "Evidence is not conclusive. A field visit is recommended.")
    if veg == "none":
        return ("not_supported", "No marked vegetation decline was seen on the plot after the loss date.",
                "The satellites did not see a decline. Cloud and small plots can hide one. A field visit is recommended "
                "before any decision.")
    if veg == "not_assessable":
        return ("inconclusive", "There was almost no vegetation on the plot before the loss date.",
                "Optical data cannot assess this claim. A field visit is recommended.")
    return ("inconclusive", "No usable optical pass was available before or after the loss date.",
            "No satellite evidence either way. A field visit is recommended.")


LIMITATIONS = [
    "Indicative evidence from free Sentinel satellite data (about 10 m per pixel). It is not a loss assessment and not proof.",
    "Radar flags calm open water. Water under tall crop or reeds can be missed, so 'no water signal' does not prove there was no flood.",
    "Vegetation (NDVI) also falls with harvest and natural maturity. A decline alone does not prove loss.",
    "Cloud limits optical passes; Sentinel-1 radar revisits about every 6 to 12 days, so a short flood can fall between passes.",
    "The method has not been validated against recorded losses. Treat the result as one input to the claims decision.",
]


# ─── Network orchestration ────────────────────────────────────────────────


async def check_claim(
    client: SentinelStatisticalClient,
    *,
    lat: float,
    lon: float,
    loss_date: date,
    peril: str = "flood",
    crop: str = "general",
    half_m: float = DEFAULT_HALF_M,
    today: date | None = None,
) -> ClaimResult:
    """Compare the plot before and after `loss_date` and grade the evidence."""
    peril = peril if peril in PERILS else "general"
    crop = normalise_crop(crop) or "general"
    today = today or datetime.now(timezone.utc).date()
    wins = split_windows(loss_date)
    bbox = bbox_around(lat, lon, half_m)
    side_m = 2 * half_m
    result = ClaimResult(
        lat=lat, lon=lon, loss_date=loss_date.isoformat(), peril=peril, crop=crop,
        area_ha=round((side_m * side_m) / 10_000.0, 2),
        windows={k: f"{v[0].isoformat()} to {v[1].isoformat()}" for k, v in wins.items()},
        thresholds={
            "water_vv_db_below": WATER_DB,
            "flood_strong_share": FLOOD_STRONG_AFTER,
            "flood_partial_share": FLOOD_PARTIAL_AFTER,
            "ndvi_marked_drop": NDVI_MARKED_ABS,
            "ndvi_moderate_drop": NDVI_MODERATE_ABS,
            "min_valid_fraction": MIN_VALID_FRACTION,
        },
        limitations=list(LIMITATIONS),
    )
    if (today - loss_date).days < MIN_AGE_AFTER_DAYS:
        result.summary = ("The loss date is too recent: the satellites have not yet "
                          "passed over the plot since.")
        result.recommendation = (f"Re-run at least {MIN_AGE_AFTER_DAYS} days after the loss date.")
        return result

    start = datetime.combine(wins["before"][0], datetime.min.time(), tzinfo=timezone.utc)
    end_day = min(wins["after"][1], today)
    end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    ndvi_points = usable_optical(await client.compute_time_series(
        bbox=bbox, start=start, end=end, dataset="sentinel-2-l2a",
        evalscript=EVALSCRIPT_S2_NDVI_CLOUDMASKED, max_cloud_cover_pct=None,
        resolution_deg=FARM_RESOLUTION_DEG))
    water_points = [p for p in await client.compute_time_series(
        bbox=bbox, start=start, end=end, dataset="sentinel-1-grd",
        evalscript=evalscript_s1_water(WATER_DB), resolution_deg=FARM_RESOLUTION_DEG)
        if p.mean is not None and p.valid_fraction >= MIN_VALID_FRACTION]

    def day(p: StatPoint) -> date:
        return p.interval_from.date()

    result.ndvi_passes = [{"date": day(p).isoformat(), "ndvi": round(p.mean, 3),
                           "plot_seen": round(p.valid_fraction, 2),
                           "window": "before" if _in(day(p), wins["before"]) else "after"}
                          for p in ndvi_points if _in(day(p), wins["before"]) or _in(day(p), wins["after"])]
    result.water_passes = [{"date": day(p).isoformat(), "water_share": round(p.mean, 3),
                            "plot_seen": round(p.valid_fraction, 2),
                            "window": "before" if _in(day(p), wins["before"]) else "after"}
                           for p in water_points if _in(day(p), wins["before"]) or _in(day(p), wins["after"])]

    w_before = [p["water_share"] for p in result.water_passes if p["window"] == "before"]
    w_after = [p["water_share"] for p in result.water_passes if p["window"] == "after"]
    n_before = [p["ndvi"] for p in result.ndvi_passes if p["window"] == "before"]
    n_after = [p["ndvi"] for p in result.ndvi_passes if p["window"] == "after"]

    result.flood_evidence, wb, wa = classify_flood(w_before, w_after)
    result.vegetation_change, nb, na = classify_vegetation(n_before, n_after)
    result.metrics = {
        "water_share_before": None if wb is None else round(wb, 3),
        "water_share_after_peak": None if wa is None else round(wa, 3),
        "ndvi_before": None if nb is None else round(nb, 3),
        "ndvi_after_low": None if na is None else round(na, 3),
        "ndvi_change": None if nb is None or na is None else round(na - nb, 3),
    }
    result.conclusion, result.summary, result.recommendation = conclude(
        peril, result.flood_evidence, result.vegetation_change)
    return result
