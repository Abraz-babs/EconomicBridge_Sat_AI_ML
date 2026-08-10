"""An advisory must survive being superseded.

`_replace_prior()` deletes every live rainfall row on each scan, which is right
for a "what is advised now" panel and wrong as a record. Observed 2026-08-10: a
Nasarawa advisory seen in the morning was gone by afternoon because that day's
scan replaced the set — nothing had failed, but there was no way to show it had
ever been issued.

These pin the two properties that make the history usable as evidence.
"""
from __future__ import annotations

import inspect
import re

from tasks import rainstorm_scan as rs


def test_the_live_feed_still_deletes_and_that_is_deliberate():
    """If _replace_prior ever stops deleting, the dashboard accumulates rows
    forever and this whole table becomes redundant — worth noticing."""
    src = inspect.getsource(rs._replace_prior)

    assert "DELETE FROM shock_events" in src


def test_every_advisory_is_archived_next_to_the_live_write():
    """The archive call must sit with the live insert, not somewhere a future
    refactor can drop it."""
    src = inspect.getsource(rs.scan_tenant)

    assert "_insert(" in src
    assert "_record_history(" in src
    live = src.index("_insert(")
    hist = src.index("_record_history(")
    assert hist > live, "archive should follow the live write"


def test_history_insert_is_idempotent_per_lga_and_observed_day():
    """A manual re-run or a task replacement mid-scan must not double-count the
    same rainfall in a record meant to be evidence."""
    src = inspect.getsource(rs._record_history)

    assert re.search(r"ON CONFLICT\s*\(\s*lga,\s*observed_date\s*\)\s*DO NOTHING",
                     src, re.I), "history write must be idempotent per LGA/day"


def test_history_records_both_dates():
    """observed_date is when it rained; advised_at is when we said so. They
    differ by IMERG latency, and an operator asking "why today?" needs both."""
    src = inspect.getsource(rs._record_history)

    assert "observed_date" in src
    # advised_at is a column default — the insert must NOT set it by hand,
    # or a backfill would stamp everything with the backfill time.
    assert "advised_at" not in src


def test_a_failed_archive_never_costs_the_operator_the_advisory():
    """Archiving is bookkeeping. If it fails, the live advisory must still be
    delivered — the reverse would trade a warning for a record."""
    src = inspect.getsource(rs.scan_tenant)

    m = re.search(r"_record_history\(.*?\)", src, re.S)
    assert m, "no _record_history call found"
    before = src[:m.start()]
    assert before.rstrip().endswith("try:") or "try:" in before[-200:], (
        "the archive write must be inside a try/except so it cannot break the scan"
    )
