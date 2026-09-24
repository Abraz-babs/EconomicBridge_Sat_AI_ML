"""Synthetic results never reach a live table or a live view (migration 0053).

Two "critical flood, 0.99" events and two NDVI anomalies made from synthetic
series with demo-injected anomalies sat on the dashboard under a LIVE chip.
These tests pin both halves of the fix.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from services.data_source import NOT_SYNTHETIC, may_store

API = Path(__file__).resolve().parents[1]


def test_only_live_uninjected_results_may_be_stored():
    assert may_store(used_live_data=True, demo_injected=False) is True
    assert may_store(used_live_data=False, demo_injected=False) is False   # modelled fallback
    assert may_store(used_live_data=False, demo_injected=True) is False    # demo flood
    assert may_store(used_live_data=True, demo_injected=True) is False


def test_the_filter_keeps_rows_recorded_before_provenance():
    """NULL = recorded before 0053; only proven synthetic rows drop out."""
    assert "COALESCE(data_source, '')" in NOT_SYNTHETIC
    assert "<> 'synthetic'" in NOT_SYNTHETIC


def test_every_live_reader_filters_synthetic_rows():
    """Any API code that SELECTs from these tables must apply NOT_SYNTHETIC in
    the same file — a new reader without it would put fakes back on screen."""
    offenders = []
    for path in list((API / "routers").glob("*.py")) + list((API / "services").glob("*.py")):
        src = path.read_text("utf-8")
        reads = re.search(r"FROM\s+(\"\{schema\}\"\.)?(shock_events|ndvi_anomalies)\b", src)
        if reads and "NOT_SYNTHETIC" not in src and "source IN" not in src:
            offenders.append(path.name)
    assert not offenders, f"reads detections without the synthetic filter: {offenders}"


def test_scan_endpoints_store_only_through_the_guard():
    from routers import cropguard_ndvi, shockguard

    for fn in (shockguard.scan_shock, cropguard_ndvi.scan_ndvi_anomaly):
        src = inspect.getsource(fn)
        assert "may_store(" in src, fn.__name__
        assert "and storable" in src, fn.__name__
