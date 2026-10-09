"""Unit tests for the claim check (no CDSE/network).

What these pin is the HONESTY of the grading: a result reaches an insurer and,
through the insurer, a farmer. The worst failures are silent ones — calling a
paddy field a flood, calling "radar saw nothing" a rejection, or grading a pass
that saw a sliver of the plot as if it saw all of it.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ING_ROOT = Path(__file__).resolve().parent.parent
if str(ING_ROOT) not in sys.path:
    sys.path.insert(0, str(ING_ROOT))

from sources.claim_check import (  # noqa: E402
    check_claim,
    classify_flood,
    classify_vegetation,
    conclude,
    split_windows,
    usable_optical,
)
from sources.sentinel_statistical import StatPoint  # noqa: E402


def _pt(d: date, mean: float | None, *, size: int = 100, nodata: int = 0,
        dataset: str = "sentinel-2-l2a") -> StatPoint:
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return StatPoint(interval_from=dt, interval_to=dt, dataset=dataset, band_name="default",
                     mean=mean, min_value=None, max_value=None, std_dev=None,
                     sample_count=size, no_data_count=nodata)


# ─── windows ─────────────────────────────────────────────────────────────

def test_event_window_opens_two_weeks_before_the_reported_date() -> None:
    """Floods build up and losses are reported late: a plot under water a few
    days before the reported date belongs to the event, not the baseline."""
    w = split_windows(date(2026, 9, 10))
    assert w["before"] == (date(2026, 7, 12), date(2026, 8, 26))
    assert w["after"] == (date(2026, 8, 27), date(2026, 10, 10))
    assert date(2026, 9, 4) >= w["after"][0]   # six days early: counted as event


def test_flood_reported_after_the_water_arrived_is_still_strong() -> None:
    """Regression (Kebbi, 1 Sep 2024): 74% water six days before the reported
    loss date was graded only partial when it fell into the baseline."""
    loss = date(2024, 9, 7)
    w = split_windows(loss)
    before = [0.03, 0.16, 0.02]                # Jul–mid Aug
    event = [0.74, 0.24, 0.11]                 # 1 Sep (D-6), then receding
    assert date(2024, 9, 1) >= w["after"][0]
    assert classify_flood(before, event)[0] == "strong"


def test_pass_seeing_a_sliver_of_the_plot_is_not_used() -> None:
    pts = [_pt(date(2026, 9, 1), 0.6, nodata=90),   # 10% of the plot seen
           _pt(date(2026, 9, 2), 0.6, nodata=10)]   # 90% seen
    assert [p.interval_from.day for p in usable_optical(pts)] == [2]


# ─── flood grading ───────────────────────────────────────────────────────

def test_strong_flood_when_water_appears_that_was_not_there() -> None:
    assert classify_flood([0.0, 0.02], [0.1, 0.65])[0] == "strong"


def test_partial_flood() -> None:
    assert classify_flood([0.01], [0.2])[0] == "partial"


def test_no_flood_signal() -> None:
    assert classify_flood([0.01, 0.0], [0.03, 0.05])[0] == "none"


def test_paddy_or_wetland_is_indeterminate_not_a_flood() -> None:
    """Water already on the plot before the loss cannot be attributed to it."""
    assert classify_flood([0.5, 0.6], [0.9])[0] == "indeterminate"


def test_no_radar_pass_after_is_insufficient() -> None:
    assert classify_flood([0.0], [])[0] == "insufficient"


# ─── vegetation grading ──────────────────────────────────────────────────

def test_marked_decline() -> None:
    assert classify_vegetation([0.62, 0.60], [0.31])[0] == "marked"


def test_moderate_decline() -> None:
    assert classify_vegetation([0.60], [0.50])[0] == "moderate"


def test_no_decline() -> None:
    assert classify_vegetation([0.55], [0.57, 0.53])[0] == "none"


def test_single_pass_dip_that_recovers_is_not_a_decline() -> None:
    """Regression (Kogi, 4 Oct 2022): one hazy pass at 0.42 between 0.72 and
    0.63 graded a dry control plot 'marked decline'."""
    assert classify_vegetation([0.59, 0.73], [0.72, 0.42, 0.63, 0.67, 0.67])[0] == "none"


def test_decline_seen_on_two_passes_is_marked() -> None:
    assert classify_vegetation([0.60, 0.62], [0.30, 0.28, 0.55])[0] == "marked"


def test_bare_plot_before_is_not_assessable() -> None:
    assert classify_vegetation([0.12], [0.05])[0] == "not_assessable"


# ─── wording: never a rejection ──────────────────────────────────────────

def test_not_supported_wording_never_rejects_and_asks_for_field_visit() -> None:
    for peril, flood, veg in (("flood", "none", "none"), ("drought", "none", "none")):
        conclusion, summary, rec = conclude(peril, flood, veg)
        assert conclusion == "not_supported"
        text = (summary + " " + rec).lower()
        assert "reject" not in text and "deny" not in text and "fraud" not in text
        assert "field visit" in text


def test_flood_with_no_water_but_crop_collapse_is_partial_not_unsupported() -> None:
    assert conclude("flood", "none", "marked")[0] == "partly_supports"


# ─── orchestration ───────────────────────────────────────────────────────

class _FakeClient:
    """Returns canned passes per dataset, the way the Statistical API would."""

    def __init__(self, optical: list[StatPoint], radar: list[StatPoint]) -> None:
        self.optical, self.radar, self.calls = optical, radar, []

    async def compute_time_series(self, *, dataset: str, start, end, **_kw):
        self.calls.append((dataset, start, end))
        return self.optical if dataset == "sentinel-2-l2a" else self.radar


def test_flood_claim_end_to_end_supports_and_reports_every_pass() -> None:
    loss = date(2026, 9, 10)
    client = _FakeClient(
        optical=[_pt(date(2026, 8, 20), 0.62), _pt(date(2026, 9, 20), 0.30)],
        radar=[_pt(date(2026, 8, 25), 0.02, dataset="sentinel-1-grd"),
               _pt(date(2026, 9, 14), 0.70, dataset="sentinel-1-grd")],
    )
    r = asyncio.run(check_claim(client, lat=12.45, lon=4.20, loss_date=loss,
                                peril="flood", today=date(2026, 10, 8)))
    assert r.flood_evidence == "strong"
    assert r.conclusion == "supports"
    assert [p["window"] for p in r.water_passes] == ["before", "after"]
    assert r.metrics["water_share_after_peak"] == 0.7
    assert r.limitations, "every result must carry its limitations"
    # the query never asks for days after today
    assert all(end.date() <= date(2026, 10, 9) for _, _, end in client.calls)


def test_too_recent_loss_makes_no_satellite_call() -> None:
    client = _FakeClient([], [])
    r = asyncio.run(check_claim(client, lat=12.45, lon=4.20, loss_date=date(2026, 10, 6),
                                today=date(2026, 10, 8)))
    assert r.conclusion == "inconclusive"
    assert client.calls == []
