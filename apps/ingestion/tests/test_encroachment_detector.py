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
