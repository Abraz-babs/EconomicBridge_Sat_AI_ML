"""Tests for the per-run cap in tasks/firms_alerts.py.

The cap exists because fire is a SECONDARY signal in the Farmland
Protection product. A 30-pixel burn front turning into 30 alert rows
drowns the conflict feed (the actual headline). These tests pin the
selection rule so a future refactor doesn't accidentally lift the cap.
"""
from __future__ import annotations

import pytest

from processors.firms_to_alerts import AlertCandidate
from tasks.firms_alerts import (
    DEFAULT_MAX_ALERTS_PER_RUN,
    write_alert_candidates,
)


def _cand(severity: str, confidence: float, lat_seed: int) -> AlertCandidate:
    """Build a candidate where every field stays inside the schema."""
    return AlertCandidate(
        tenant_id="kebbi",
        alert_type="fire",
        severity=severity,
        confidence_score=confidence,
        latitude=12.0 + lat_seed * 0.001,
        longitude=4.5,
        satellite_source="NASA FIRMS / VIIRS (test)",
        satellite_pass_time=__import__("datetime").datetime(
            2026, 5, 20, tzinfo=__import__("datetime").timezone.utc
        ),
        model_name="nasa_firms",
        model_version="test",
        model_input_hash=f"hash-{lat_seed:04d}",
        affected_area_ha=10.0,
        livelihoods_at_risk=None,
        economic_value_ngn=None,
        predicted_breach_hours=None,
        human_review_required=True,
    )


class _FakeSession:
    """Stub AsyncSession that records writes without touching a DB."""

    def __init__(self) -> None:
        self.executed_hashes: list[str] = []
        self.committed = 0

    async def execute(self, stmt, params=None):  # noqa: ANN001 — duck-typed
        # set_tenant_schema fires `SET search_path ...` with no params.
        if params and "h" in params:
            return _NoMatchResult()
        if params and "model_input_hash" in params:
            self.executed_hashes.append(params["model_input_hash"])
        return _NoMatchResult()

    async def commit(self) -> None:
        self.committed += 1


class _NoMatchResult:
    def first(self):
        return None


@pytest.mark.asyncio
async def test_default_cap_keeps_only_top_two():
    """Five inbound candidates -> two persisted; three dropped by cap."""
    candidates = [
        _cand("medium", 0.78, 1),
        _cand("critical", 0.92, 2),
        _cand("high", 0.92, 3),
        _cand("low", 0.78, 4),
        _cand("high", 0.85, 5),
    ]
    sess = _FakeSession()

    result = await write_alert_candidates(
        sess, tenant_id="kebbi", candidates=candidates
    )

    assert result.candidates == 5
    assert result.inserted == 2
    assert result.skipped_capped == 3
    # The two survivors must be the critical first, then the higher-confidence
    # of the two high-severity rows.
    assert sess.executed_hashes == ["hash-0002", "hash-0003"]


@pytest.mark.asyncio
async def test_explicit_max_per_run_overrides_default():
    candidates = [_cand("high", 0.9, i) for i in range(6)]
    sess = _FakeSession()
    result = await write_alert_candidates(
        sess, tenant_id="kebbi", candidates=candidates, max_per_run=4,
    )
    assert result.inserted == 4
    assert result.skipped_capped == 2


@pytest.mark.asyncio
async def test_max_per_run_zero_inserts_nothing():
    candidates = [_cand("critical", 0.95, i) for i in range(3)]
    sess = _FakeSession()
    result = await write_alert_candidates(
        sess, tenant_id="kebbi", candidates=candidates, max_per_run=0,
    )
    assert result.inserted == 0
    assert result.skipped_capped == 3


def test_default_cap_constant_is_documented():
    # Sanity check so future grep-replaces against this number are noticed.
    assert DEFAULT_MAX_ALERTS_PER_RUN == 2
