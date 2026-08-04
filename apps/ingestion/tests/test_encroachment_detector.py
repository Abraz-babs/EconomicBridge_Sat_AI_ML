"""Unit tests for the encroachment fusion (pure function, no DB/network)."""
from __future__ import annotations

import sys
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from tasks.encroachment_detector import (  # noqa: E402
    ALERT_THRESHOLD, MIN_POINTS, _impact_estimate, compute_encroachment,
    nightlight_newlight,
)


# ─── VIIRS new-light component ─────────────────────────────────────────────


def test_newlight_flags_light_in_dark_area():
    """A meaningful radiance increase where it was dark → strong signal."""
    assert nightlight_newlight(current=4.0, baseline=0.2) > 0.6


def test_newlight_ignores_already_lit_places():
    """An existing town (bright baseline) is not 'new activity' → 0."""
    assert nightlight_newlight(current=30.0, baseline=12.0) == 0.0


def test_newlight_zero_when_no_change_or_missing():
    assert nightlight_newlight(current=0.2, baseline=0.2) == 0.0
    assert nightlight_newlight(current=None, baseline=0.1) == 0.0
    assert nightlight_newlight(current=3.0, baseline=None) == 0.0


def test_newlight_raises_score_when_ndvi_sar_quiet():
    """Year-round: with NDVI rising (greening) + flat SAR, a new light still
    lifts the encroachment score above the no-nightlight baseline."""
    ndvi = [0.30 + 0.01 * i for i in range(12)]   # greening → no loss
    sar = [-8.0 for _ in range(12)]                # flat → no change
    quiet = compute_encroachment(ndvi, sar, 0, nightlight=0.0)
    lit = compute_encroachment(ndvi, sar, 0, nightlight=0.8)
    assert quiet is not None and lit is not None
    assert lit.score > quiet.score
    assert lit.nightlight == 0.8


def test_impact_estimate_scales_with_severity():
    """Higher severity → bigger extent + shorter conflict-risk window."""
    crit = _impact_estimate("critical", 0.85)
    med = _impact_estimate("medium", 0.50)
    # (area_ha, livelihoods, econ_ngn, breach_hours)
    assert crit[0] > med[0]                 # critical covers more ha
    assert crit[1] > med[1]                 # more livelihoods
    assert crit[2] > med[2]                 # more economic value
    assert crit[3] < med[3]                 # critical breaches sooner


def test_impact_estimate_is_internally_consistent():
    """Livelihoods and economic value derive from the area at fixed ratios."""
    area, livelihoods, econ_ngn, breach = _impact_estimate("medium", 0.52)
    assert area >= 1
    assert livelihoods == round(area * 4.6)
    assert econ_ngn == area * 200_000
    assert breach in (24, 48, 72, 96)


def test_thin_data_returns_none():
    assert compute_encroachment([0.5, 0.5], [-10, -10], 0) is None


def test_flat_series_scores_low_no_alert():
    flat = [0.50] * 10
    sar = [-12.0] * 10
    sig = compute_encroachment(flat, sar, 0)
    assert sig is not None
    assert sig.score < ALERT_THRESHOLD
    assert sig.severity == "low"


def test_vegetation_loss_plus_sar_change_raises_score():
    # NDVI baseline ~0.6 then a sharp recent drop; SAR baseline stable then jump
    ndvi = [0.60, 0.61, 0.59, 0.60, 0.62, 0.61, 0.30, 0.28, 0.31]
    sar = [-12.0, -12.1, -11.9, -12.0, -12.2, -12.1, -8.0, -8.2, -7.9]
    sig = compute_encroachment(ndvi, sar, fire_count=0)
    assert sig is not None
    assert sig.ndvi_z < 0                      # detected a loss
    assert sig.sar_z > 1.0                     # detected disturbance
    assert sig.score >= ALERT_THRESHOLD        # clears the watch bar
    assert sig.severity in ("medium", "high", "critical")


def test_fire_boosts_the_score():
    ndvi = [0.5] * 10
    sar = [-12.0] * 10
    no_fire = compute_encroachment(ndvi, sar, fire_count=0)
    with_fire = compute_encroachment(ndvi, sar, fire_count=8)
    assert with_fire.score > no_fire.score


def test_vegetation_gain_alone_does_not_alert():
    # Wet-season greening: NDVI rises sharply, SAR flat, no fire. This must
    # NOT be flagged as land-disturbance risk (the bug we fixed).
    ndvi = [0.30, 0.31, 0.29, 0.30, 0.32, 0.31, 0.62, 0.60, 0.63]
    sar = [-12.0] * 9
    sig = compute_encroachment(ndvi, sar, fire_count=0)
    assert sig is not None
    assert sig.ndvi_z > 0                       # it's a GAIN
    assert sig.score < ALERT_THRESHOLD          # but no alert
    assert sig.components["ndvi_loss"] == 0.0   # gain contributes nothing


def test_components_present():
    ndvi = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.4, 0.4, 0.4]
    sar = [-12, -12, -12, -12, -12, -12, -9, -9, -9]
    sig = compute_encroachment(ndvi, sar, 1)
    assert set(sig.components) >= {"ndvi_loss", "sar_change", "fire"}
    assert len(ndvi) >= MIN_POINTS


# ─── an empty CDSE read is not a reading ──────────────────────────────────
# Regression tests for live data destruction found on 2026-07-28. The monthly
# -quota breaker in sources/sentinel_statistical.py returns [] rather than
# raising, so once the CDSE quota blew (~2026-07-12) an exhausted quota slipped
# past the CopernicusError handler and looked exactly like a successful scan of
# a quiet LGA. Each such "scan" then had _write_crop_health replace that LGA's
# real NDVI with NULL. By the time it was caught, 306 of 447 crop_health rows
# were nulled and FCT had none left at all.


def test_empty_series_short_circuits_before_any_write() -> None:
    """The guard must sit between the fetch and BOTH writes — the crop_health
    upsert and the alert_events delete. If it moved below either, an empty read
    would still destroy that LGA's state."""
    import inspect

    from tasks import encroachment_detector

    src = inspect.getsource(encroachment_detector.detect_per_lga_for_tenant)
    fetch = src.index("_fetch_lga_series(client")
    guard = src.index("if not ndvi and not sar:")
    health = src.index("_write_crop_health(")
    delete = src.index("DELETE FROM alert_events")
    assert fetch < guard < health, "guard must precede the crop_health write"
    assert guard < delete, "guard must precede the alert_events delete"
    assert "continue" in src[guard:health]


def test_a_no_data_sweep_reports_not_checked_not_zero_alerts() -> None:
    """"0 alert(s) / 0 scanned" is true but reads as calm. The sweep must say it
    did not look, and the run must be recorded FAILED so the panel shows the
    miss — the same distinction shockguard_scan already draws."""
    import inspect

    from tasks import encroachment_detector as ed
    from tasks.shockguard_scan import NO_DATA_REASON as SHOCK_REASON

    assert ed.NO_DATA_REASON == SHOCK_REASON        # one sentence, both sweeps

    src = inspect.getsource(ed.detect_per_lga_for_tenant)
    assert "if evaluated == 0:" in src
    assert "NOT CHECKED" in src

    caller = inspect.getsource(ed.run_encroachment_sweep)
    assert "NO_DATA_REASON if evaluated == 0 else None" in caller


def test_roi_fallback_is_not_mistaken_for_a_no_data_run() -> None:
    """The ROI path returns None, not 0, for the read count. `evaluated == 0`
    must therefore leave it alone — flagging it would mark every credential-less
    environment as a failed sweep."""
    import inspect

    from tasks import encroachment_detector as ed

    src = inspect.getsource(ed.detect_per_lga_for_tenant)
    assert "return await detect_for_tenant(session, tenant), None" in src
    assert (None == 0) is False                     # noqa: E711 — the premise


# ─── a degenerate baseline is not evidence ────────────────────────────────
# Same defect as shockguard_scan's compute_shock, found the same way on
# 2026-07-28. `pstdev(x) or 1e-6` caught only an EXACT zero, so three
# near-identical readings divided an ordinary wobble by ~0.002 and saturated
# that component to 1.0. Because `primary` is the MAX component, a lone
# flat-baseline signal scored 0.6 — twice ALERT_THRESHOLD. A quiet LGA plus
# speckle raised an encroachment watch on the flagship module.


def test_flat_sar_baseline_alone_does_not_raise_a_watch():
    ndvi = [0.50, 0.51, 0.49, 0.50, 0.52, 0.50, 0.50, 0.51, 0.49]
    sar = [-12.000, -12.001, -12.000, -12.0005, -12.001, -12.000,
           -12.30, -12.30, -12.30]
    sig = compute_encroachment(ndvi, sar, fire_count=0)
    assert sig is not None
    assert sig.sar_z == 0.0                     # unjudgeable -> contributes nothing
    assert sig.score < ALERT_THRESHOLD


def test_flat_ndvi_baseline_contributes_nothing_rather_than_everything():
    ndvi = [0.500, 0.5001, 0.500, 0.5002, 0.500, 0.5001, 0.48, 0.48, 0.48]
    sar = [-12.0, -12.4, -11.8, -12.2, -11.9, -12.1, -12.0, -12.1, -11.9]
    sig = compute_encroachment(ndvi, sar, fire_count=0)
    assert sig is not None
    assert sig.ndvi_z == 0.0


def test_a_real_multi_signal_event_still_alerts():
    """The floors must not suppress genuine detections — the other components
    still count, so corroborated events are untouched."""
    ndvi = [0.62, 0.60, 0.63, 0.61, 0.59, 0.62, 0.30, 0.28, 0.31]
    sar = [-11.2, -12.4, -11.8, -12.9, -11.5, -12.1, -8.0, -8.2, -7.9]
    sig = compute_encroachment(ndvi, sar, fire_count=6)
    assert sig is not None
    assert sig.score >= ALERT_THRESHOLD


def test_no_divide_by_epsilon_remains_in_the_fusion():
    """Code lines only — the comment above the fix deliberately quotes the old
    pattern as a warning, so a whole-source check would match its own note."""
    import inspect

    from tasks import encroachment_detector

    src = inspect.getsource(encroachment_detector.compute_encroachment)
    code = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    assert not any("or 1e-6" in ln for ln in code)


# ─── absence of a measurement must not overwrite a measurement ────────────
# The July incident's last surviving corner. The caller skips an LGA only when
# BOTH signals are empty — but under heavy cloud (i.e. most of the wet season)
# Sentinel-1 SAR returns fine while Sentinel-2 optical returns nothing. That
# pair sails past the caller and reaches _write_crop_health with an empty NDVI
# series, which then DELETE+INSERTs the LGA's real reading away as NULL.


def test_an_empty_ndvi_series_writes_nothing_at_all():
    """crop_health is replaced, not merged, so a write with no reading is a
    delete. The function must return before touching the table."""
    import inspect

    from tasks import encroachment_detector

    src = inspect.getsource(encroachment_detector._write_crop_health)
    guard = src.index("if not ndvi_series:")
    delete = src.index("DELETE FROM crop_health")
    assert guard < delete, "the no-reading guard must precede the delete"
    assert "return" in src[guard:delete]


def test_the_guard_cannot_be_satisfied_by_the_callers_check_alone():
    """The caller's `not ndvi and not sar` is an AND — it lets the
    cloud case (sar yes, ndvi no) through. Pinning both guards so neither is
    removed on the assumption the other covers it."""
    import inspect

    from tasks import encroachment_detector

    caller = inspect.getsource(encroachment_detector.detect_per_lga_for_tenant)
    assert "if not ndvi and not sar:" in caller          # caller: both empty
    writer = inspect.getsource(encroachment_detector._write_crop_health)
    assert "if not ndvi_series:" in writer               # writer: optical empty


def test_ndvi_value_is_only_computed_when_a_reading_exists():
    """`ndvi_series[-1] if ndvi_series else None` was what let None through to
    classify_health and into the column. There should no longer be a None path."""
    import inspect

    from tasks import encroachment_detector

    src = inspect.getsource(encroachment_detector._write_crop_health)
    assert "if ndvi_series else None" not in src


# ─── cloud is not drought ─────────────────────────────────────────────────
# Found 2026-08-03 verifying four "critical drought" calls in Ghana. Two rested
# on NDVI readings of -0.0219 and -0.0255. Negative NDVI means red exceeded
# near-infrared — vegetation cannot do that. It is residual cloud the SCL mask
# missed, or open water. Averaged into the recent window it is indistinguishable
# from a vegetation collapse, and the detector sees only `mean`.


class _Pt:
    """Minimal StatPoint stand-in."""

    def __init__(self, mean, sample_count=1000, no_data_count=0):
        self.mean = mean
        self.sample_count = sample_count
        self.no_data_count = no_data_count

    @property
    def valid_count(self):
        return max(0, self.sample_count - self.no_data_count)

    @property
    def valid_fraction(self):
        return self.valid_count / self.sample_count if self.sample_count else 0.0


def test_negative_ndvi_is_rejected_as_cloud_or_water():
    """The exact values behind the Ellembelle and Hohoe calls."""
    from tasks.encroachment_detector import _usable_ndvi

    assert _usable_ndvi(_Pt(-0.0219)) is False
    assert _usable_ndvi(_Pt(-0.0255)) is False
    assert _usable_ndvi(_Pt(0.0)) is False


def test_genuinely_bare_soil_is_still_a_real_reading():
    """The guard must not swallow the poor readings the module exists to find.
    Bare soil sits around 0.10-0.15 and is a legitimate, alarming measurement."""
    from tasks.encroachment_detector import _usable_ndvi

    assert _usable_ndvi(_Pt(0.12)) is True
    assert _usable_ndvi(_Pt(0.08)) is True


def test_a_mean_over_a_sliver_of_the_box_is_not_comparable():
    """sampleCount is the box size and stays constant, so it never revealed
    masking. valid_fraction does."""
    from tasks.encroachment_detector import _usable_ndvi

    mostly_clouded = _Pt(0.55, sample_count=1000, no_data_count=950)
    assert mostly_clouded.valid_fraction == 0.05
    assert _usable_ndvi(mostly_clouded) is False
    assert _usable_ndvi(_Pt(0.55, sample_count=1000, no_data_count=300)) is True


def test_missing_nodata_field_does_not_discard_everything():
    """If the API omits noDataCount we must degrade to 'assume valid', not
    silently drop every interval and report a dead feed."""
    from tasks.encroachment_detector import _usable_ndvi

    assert _Pt(0.6, sample_count=1000, no_data_count=0).valid_fraction == 1.0
    assert _usable_ndvi(_Pt(0.6)) is True


# ─── the sweep must not render at farm resolution ─────────────────────────
# Measured 2026-08-04: 88 Statistical calls/day at ~10 PU each, ~90% of the
# 30,000 PU month. Each call rendered ~73,000 pixels (3 km box / 11 m = 270 x
# 270, exactly the sampleCount seen in production) to produce ONE number — the
# mean over the box. The precision was thrown away by the aggregation.


def test_lga_sweep_uses_its_own_resolution_not_farm_checks():
    """FARM_RESOLUTION_DEG (~11 m) is right for Farm Check, where a user is
    inspecting one farm. Reusing it for a whole-LGA mean buys nothing and costs
    the quota. They must stay separate constants."""
    from sources.farm_check import FARM_RESOLUTION_DEG
    from tasks.encroachment_detector import LGA_RESOLUTION_DEG

    assert LGA_RESOLUTION_DEG > FARM_RESOLUTION_DEG
    assert FARM_RESOLUTION_DEG == 0.0001, "Farm Check must stay at native res"


def test_the_sweep_renders_a_sane_number_of_samples():
    """Enough for a stable mean, not so coarse that one sample mixes clear and
    cloudy ground — which would change masking behaviour, not just cost."""
    from tasks.encroachment_detector import LGA_BOX_HALF_M, LGA_RESOLUTION_DEG

    box_deg = (2 * LGA_BOX_HALF_M) / 111_320.0
    per_side = box_deg / LGA_RESOLUTION_DEG
    assert 40 <= per_side <= 150, f"{per_side:.0f} samples per side"
    assert per_side ** 2 < 25_000, "still rendering far more than a mean needs"


def test_both_sweep_fetches_use_the_lga_resolution():
    import inspect

    from tasks import encroachment_detector

    src = inspect.getsource(encroachment_detector._fetch_lga_series)
    assert src.count("resolution_deg=LGA_RESOLUTION_DEG") == 2
    assert "FARM_RESOLUTION_DEG" not in src
