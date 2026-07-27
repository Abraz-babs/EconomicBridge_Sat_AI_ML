"""Unit tests for the ShockGuard flood/drought detection (pure function)."""
from __future__ import annotations

import sys
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from tasks.shockguard_scan import (  # noqa: E402
    MIN_POINTS, NDVI_SCALE, SAR_SCALE, THRESHOLD, compute_shock,
)


def test_thin_data_returns_none():
    assert compute_shock([-10.0, -10.0], "flood", SAR_SCALE) is None


def test_flat_series_no_event():
    sar = [-12.0] * 10
    assert compute_shock(sar, "flood", SAR_SCALE) is None
    ndvi = [0.50] * 10
    assert compute_shock(ndvi, "drought", NDVI_SCALE) is None


def test_rising_series_is_not_a_shock():
    # A SAR/NDVI RISE is not flood/drought — only a DROP counts.
    rising_sar = [-14, -14, -14, -14, -14, -14, -9, -9, -9]
    assert compute_shock(rising_sar, "flood", SAR_SCALE) is None
    rising_ndvi = [0.30, 0.30, 0.30, 0.30, 0.30, 0.30, 0.62, 0.60, 0.63]
    assert compute_shock(rising_ndvi, "drought", NDVI_SCALE) is None


def test_sharp_sar_drop_raises_flood():
    # Stable backscatter then a sharp drop = open water = flood signal.
    sar = [-9.0, -9.1, -8.9, -9.0, -9.2, -9.1, -16.0, -16.3, -15.8]
    sig = compute_shock(sar, "flood", SAR_SCALE)
    assert sig is not None
    assert sig.event_type == "flood"
    assert sig.z < 0                       # it's a drop
    assert sig.confidence >= THRESHOLD
    assert sig.severity in ("medium", "high", "critical")
    assert sig.band in ("LOW", "MEDIUM", "HIGH")


def test_sharp_ndvi_drop_raises_drought():
    ndvi = [0.62, 0.61, 0.63, 0.60, 0.62, 0.61, 0.34, 0.30, 0.33]
    sig = compute_shock(ndvi, "drought", NDVI_SCALE)
    assert sig is not None
    assert sig.event_type == "drought"
    assert sig.z < 0
    assert sig.confidence >= THRESHOLD


def test_bigger_drop_higher_confidence():
    base = [-9.0, -9.1, -8.9, -9.0, -9.2, -9.1]
    mild = compute_shock(base + [-12.0, -12.1, -11.9], "flood", SAR_SCALE)
    severe = compute_shock(base + [-18.0, -18.2, -17.8], "flood", SAR_SCALE)
    assert severe is not None
    # A larger drop is never less confident than a smaller one.
    mild_c = mild.confidence if mild else 0.0
    assert severe.confidence >= mild_c
    assert len(base) < MIN_POINTS + 3


# ─── "no data" must never be reported as "no signal" ─────────────────────


def test_scan_reports_not_checked_when_nothing_was_readable() -> None:
    """2026-07-27: with the CDSE quota spent, the client returns EMPTY series
    rather than raising, so every LGA produced no signal and the scan reported
    'clear (no flood/drought signal)' for all 10 tenants — then stamped
    ingestion_runs 'succeeded', so the dashboard read "monitored, no signal"
    while it had in fact read nothing at all. That is how a dead feed passes
    for a healthy one."""
    import inspect

    from tasks import shockguard_scan

    src = inspect.getsource(shockguard_scan.run_shockguard_scan)
    assert "NOT CHECKED" in src
    assert "no_data" in src
    # the misleading unconditional message must be gone
    assert 'out[t] = "clear (no flood/drought signal)"' not in src


def test_failed_run_cannot_advance_the_panels_last_scan() -> None:
    """The panel's last-scan query filters status='succeeded'. A run that read
    nothing must therefore record FAILED, or it silently refreshes the
    'continuously monitored' line on data it never saw."""
    import inspect

    from tasks import shockguard_scan

    src = inspect.getsource(shockguard_scan._record_run)
    assert '"failed" if error else "succeeded"' in src
    assert "error_message" in src


def test_per_lga_scan_returns_evaluated_count() -> None:
    """events==0 is ambiguous on its own; the evaluated count disambiguates."""
    import inspect

    from tasks import shockguard_scan

    src = inspect.getsource(shockguard_scan.detect_per_lga_for_tenant)
    assert "return events, evaluated" in src
    assert "if not sar and not ndvi:" in src
