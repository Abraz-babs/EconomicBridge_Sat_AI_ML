"""Encroachment watch history — the record that survives the live refresh.

The per-LGA sweep deletes an LGA's watch on every successful read and
re-inserts only if the signal still clears. That is right for the live panel,
but it means a watch stops existing the moment the LGA reads calm. These tests
pin the append-only record that keeps it (migration 0045), because the
operator's requirement is to "not miss anything".
"""
from __future__ import annotations

import pytest

from tasks import encroachment_detector as ed


class _Sig:
    severity = "medium"
    score = 0.56
    components = {"ndvi_z": -1.2, "sar_z": 2.1}


class _Session:
    def __init__(self, fail: bool = False) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.fail = fail

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN202
        if self.fail:
            raise RuntimeError("history table missing")
        self.sql.append(" ".join(str(stmt).split()))
        self.params.append(params or {})
        return None


@pytest.mark.asyncio
async def test_history_row_is_written_with_the_watch() -> None:
    s = _Session()
    await ed._record_watch_history(
        s, tenant="kebbi", signal=_Sig(), lga="Gwandu", lon=4.1, lat=12.5,
        zone_name="Land-surface change risk (LGA-level) near Gwandu",
        area_ha=45, livelihoods=207,
    )
    assert len(s.sql) == 1
    sql = s.sql[0]
    assert "INSERT INTO encroachment_watch_history" in sql
    p = s.params[0]
    assert p["lga"] == "Gwandu"
    assert p["severity"] == "medium"
    assert p["score"] == 0.56
    assert p["livelihoods"] == 207


@pytest.mark.asyncio
async def test_same_lga_same_day_cannot_double_count() -> None:
    """A re-run or manual full sweep must not inflate the evidence record."""
    s = _Session()
    await ed._record_watch_history(
        s, tenant="kebbi", signal=_Sig(), lga="Gwandu", lon=4.1, lat=12.5,
        zone_name="z", area_ha=1, livelihoods=1,
    )
    assert "ON CONFLICT (lga, observed_date) DO NOTHING" in s.sql[0]


@pytest.mark.asyncio
async def test_history_failure_never_breaks_the_scan() -> None:
    """History is valuable, but never at the cost of the detection itself.

    A raised exception here would lose the alert that was just written, which
    is strictly worse than losing the history row.
    """
    s = _Session(fail=True)
    await ed._record_watch_history(  # must not raise
        s, tenant="kebbi", signal=_Sig(), lga="Gwandu", lon=4.1, lat=12.5,
        zone_name="z", area_ha=1, livelihoods=1,
    )


@pytest.mark.asyncio
async def test_no_lga_writes_nothing() -> None:
    """The ROI fallback can have no representative LGA; the table requires one."""
    s = _Session()
    await ed._record_watch_history(
        s, tenant="kebbi", signal=_Sig(), lga=None, lon=None, lat=None,
        zone_name="z", area_ha=1, livelihoods=1,
    )
    assert s.sql == []


def test_live_refresh_is_unchanged() -> None:
    """The delete-then-insert refresh must stay exactly as it was.

    History is additive. If this ever fails, someone has changed the live
    behaviour while intending only to add a record.
    """
    import inspect

    src = inspect.getsource(ed.detect_per_lga_for_tenant)
    assert "DELETE FROM alert_events WHERE model_name = :m" in src
    assert "AND status = 'pending_review' AND lga = :lga" in src
