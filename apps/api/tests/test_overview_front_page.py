"""The front page reads these /overview/stats fields; keep them honest."""
from datetime import datetime, timezone

from routers.overview import LAND_CHANGE_MODEL, _latest_advisory
from schemas.overview import LastAdvisory, OverviewStatsData


def _adv(day: int, region: str, lga: str, n: int) -> LastAdvisory:
    return LastAdvisory(
        sent_at=datetime(2026, 9, day, 8, 5, tzinfo=timezone.utc),
        region=region, lga=lga, recipients=n,
    )


def test_latest_advisory_is_the_most_recent_across_tenants():
    found = [_adv(18, "Kebbi", "Argungu", 11), _adv(22, "Kebbi", "Shanga", 11),
             _adv(20, "Zamfara", "Gusau", 3)]
    latest = _latest_advisory(found)
    assert latest is not None and latest.lga == "Shanga" and latest.sent_at.day == 22


def test_no_advisory_yet_is_none_not_a_made_up_one():
    assert _latest_advisory([]) is None


def test_last_advisory_carries_counts_only_never_people():
    # A name or phone field here would put PII on a public page.
    assert set(LastAdvisory.model_fields) == {"sent_at", "region", "lga", "recipients"}


def test_new_fields_default_so_older_payloads_stay_valid():
    data = OverviewStatsData(
        tenants_live=10, lgas_mapped=447, settlements_scored=76995,
        crop_detections=0, satellite_observations=0, live_sources=[], cards=[],
        generated_at=datetime.now(timezone.utc),
    )
    assert data.farmland_greened_ha == 0 and data.land_changes == 0
    assert data.last_advisory is None


def test_land_changes_count_the_live_detector_only():
    assert LAND_CHANGE_MODEL == "land_change_v1"


class _Result:
    def __init__(self, first=None, scalar=None, rows=()):
        self._first, self._scalar, self._rows = first, scalar, list(rows)

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar

    def all(self):
        return self._rows


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Answers the core Overview query; the later-table reads can be made to fail."""

    def __init__(self, fail_later: bool):
        self.fail_later = fail_later

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "information_schema.tables" in sql:
            return _Result(rows=[("tenant_kebbi", n) for n in (
                "lga_season_vegetation", "alert_events",
                "rainfall_advisory_history", "alert_subscribers")])
        if sql.startswith("SET search_path"):
            return _Result()
        if "village_light" in sql:
            return _Result(first=(14086, 0, 5))
        if self.fail_later:
            raise RuntimeError("column does not exist")
        if "greened_on_crops_ha" in sql:
            return _Result(scalar=2_400_000.4)
        if "alert_events" in sql:
            return _Result(scalar=46)
        if "alert_subscribers" in sql:
            return _Result(scalar=11)
        if "COUNT(*) FROM rainfall_advisory_history" in sql:
            return _Result(scalar=4)
        if "ORDER BY sms_dispatched_at" in sql:
            return _Result(first=(datetime(2026, 9, 22, 8, 5, tzinfo=timezone.utc), "Shanga", 11))
        return _Result(scalar=0, first=None)


class _Req:
    class state:
        trace_id = None


def _run(session):
    import asyncio
    from uuid import uuid4

    from routers import overview

    _Req.state.trace_id = uuid4()
    return asyncio.run(overview.overview_stats(_Req(), session)).data


def test_front_page_figures_sum_from_the_later_tables():
    data = _run(_FakeSession(fail_later=False))
    assert data.land_changes == 46 and data.sms_subscribers == 11
    assert data.last_advisory is not None and data.last_advisory.lga == "Shanga"
    assert data.farmland_greened_ha == 2_400_000


def test_a_failing_later_table_never_breaks_the_overview():
    data = _run(_FakeSession(fail_later=True))
    assert data.settlements_scored > 0          # core cards still computed
    assert data.land_changes == 0 and data.last_advisory is None
