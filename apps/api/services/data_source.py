"""Live vs synthetic — the one rule every detection write and read obeys.

The on-demand ShockGuard and NDVI scans can run on a synthetic series (when
live data is missing, or on request) and can inject an anomaly for a demo.
That is fine on screen. It is not fine in a live table: two "critical flood,
0.99" events and two NDVI anomalies made that way sat on the dashboard under
a LIVE chip until 2026-09-24 (proof in migration 0053).

So:
* a result may be STORED only if it came from live satellite data with
  nothing injected (`may_store`), and is stored with data_source = 'live';
* every live view reads through NOT_SYNTHETIC, which keeps rows recorded
  before provenance was tracked (NULL) and drops only proven synthetic ones —
  which stay in the database, per the rule that no record goes.
"""
from __future__ import annotations

LIVE = "live"
SYNTHETIC = "synthetic"

# NULL-safe: rows from before migration 0053 carry NULL and stay visible.
NOT_SYNTHETIC = "COALESCE(data_source, '') <> 'synthetic'"

STORED_ONLY_WHEN_LIVE = (
    "Shown only: results from modelled or demo data are never stored as detections."
)


def may_store(*, used_live_data: bool, demo_injected: bool) -> bool:
    """Whether a scan result may enter a live table."""
    return used_live_data and not demo_injected
