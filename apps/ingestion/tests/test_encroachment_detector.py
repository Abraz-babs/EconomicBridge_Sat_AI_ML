"""Unit tests for the encroachment fusion (pure function, no DB/network)."""
from __future__ import annotations

import sys
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from tasks.encroachment_detector import (  # noqa: E402
    ALERT_THRESHOLD, MIN_POINTS, compute_encroachment,
)


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


def test_components_and_weights_present():
    ndvi = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.4, 0.4, 0.4]
    sar = [-12, -12, -12, -12, -12, -12, -9, -9, -9]
    sig = compute_encroachment(ndvi, sar, 1)
    assert set(sig.components) >= {"ndvi", "sar", "fire", "weights"}
    assert abs(sum(sig.components["weights"].values()) - 1.0) < 1e-9
    assert len(ndvi) >= MIN_POINTS
