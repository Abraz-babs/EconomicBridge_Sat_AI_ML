"""The alert record's grouping — pure, no database.

Cases are the real ones seen on 2026-09-24: Suru's watch read on 28 Aug, 9 Sep
and 21 Sep is ONE continuing watch; Fakai read 29 Aug and 10 Sep and then calm
is one ENDED watch.
"""
from __future__ import annotations

from datetime import date

from schemas.farmland import RecordEntryKind, RecordEntryStatus
from services.farmland_record import (
    EPISODE_GAP_DAYS,
    Patch,
    WatchRead,
    group_scans,
    group_watches,
    sigma_of,
)


def read(lga: str, day: date, score: float = 0.4, zone: str | None = None) -> WatchRead:
    return WatchRead(
        lga=lga, day=day, severity="medium", score=score, lon=4.0, lat=12.0,
        area_ha=19, livelihoods=87,
        zone_name=zone or f"Land-surface change risk (LGA-level) near {lga}: radar land-surface change 1.6σ",
    )


def test_reads_one_revisit_apart_are_one_episode():
    reads = [read("Suru", date(2026, 8, 28), 0.453), read("Suru", date(2026, 9, 9), 0.368),
             read("Suru", date(2026, 9, 21), 0.413)]
    [e] = group_watches(reads, active={("Suru", date(2026, 9, 21))})
    assert e.kind is RecordEntryKind.RADAR_WATCH
    assert (e.start, e.end, len(e.reads)) == (date(2026, 8, 28), date(2026, 9, 21), 3)
    assert e.status is RecordEntryStatus.ACTIVE
    assert e.peak_score == 0.453


def test_a_gap_longer_than_one_revisit_starts_a_new_episode():
    gap = EPISODE_GAP_DAYS + 1
    reads = [read("Jega", date(2026, 8, 1)), read("Jega", date(2026, 8, 1).fromordinal(date(2026, 8, 1).toordinal() + gap))]
    assert len(group_watches(reads, active=set())) == 2


def test_a_watch_not_on_the_live_list_has_ended():
    reads = [read("Fakai", date(2026, 8, 29)), read("Fakai", date(2026, 9, 10))]
    [e] = group_watches(reads, active=set())
    assert e.status is RecordEntryStatus.ENDED


def test_active_means_the_latest_read_is_the_live_watch():
    """A live watch raised on an EARLIER day of the same LGA does not make a
    later episode active — only the episode whose last read it is."""
    reads = [read("Bunza", date(2026, 7, 1)), read("Bunza", date(2026, 9, 24))]
    early, late = sorted(group_watches(reads, active={("Bunza", date(2026, 9, 24))}),
                         key=lambda e: e.start)
    assert early.status is RecordEntryStatus.ENDED
    assert late.status is RecordEntryStatus.ACTIVE


def test_sigma_is_read_from_the_alert_text():
    assert sigma_of("near Dandi: radar land-surface change 1.1σ") == 1.1
    assert sigma_of("near Augie: rangeland that greened in 2024") is None
    assert sigma_of(None) is None


def test_the_peak_read_supplies_severity_sigma_and_summary():
    reads = [read("Jega", date(2026, 9, 3), 0.542, "radar land-surface change 2.1σ"),
             read("Jega", date(2026, 9, 15), 0.609, "radar land-surface change 2.4σ")]
    [e] = group_watches(reads, active=set())
    assert e.peak_sigma == 2.4 and e.peak_score == 0.609
    assert [r.sigma for r in e.reads] == [2.1, 2.4]


def test_scans_group_by_day_and_keep_every_patch_position():
    day = date(2026, 9, 23)
    patches = [Patch(day, "Ngaski", 4.56, 10.10), Patch(day, "Ngaski", 4.55, 10.11),
               Patch(day, "Maiyama", 4.33, 12.07), Patch(date(2026, 9, 21), "Jega", 4.3, 12.2)]
    scans = sorted(group_scans(patches, RecordEntryStatus.SUPERSEDED), key=lambda e: e.start)
    assert [s.patches for s in scans] == [1, 3]
    assert scans[1].lgas == 2 and len(scans[1].points) == 3
    assert all(s.status is RecordEntryStatus.SUPERSEDED for s in scans)
