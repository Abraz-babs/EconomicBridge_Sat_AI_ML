"""The Farmland alert record — every alert the platform raised, past and present.

The live list (GET /farmland/alerts) is the PRESENT: the daily sweep replaces an
LGA's watch each time it re-reads it, and a calm read removes it. The record is
the PAST as well, browsable by year and month under the map, and every entry
can be put back on the map and into the Spotlight.

Three sources, all already retained:

* `encroachment_watch_history` (migration 0045) — one row per LGA per day a
  radar watch was raised, kept permanently. Reads of the same LGA up to one
  revisit apart are one continuing watch, so they are grouped into EPISODES:
  Suru read 28 Aug, 9 Sep and 21 Sep is one entry with three reads, not three.
* `alert_events` — alerts an officer acknowledged, resolved or dismissed (the
  sweep never deletes those), and the live land-change patches.
* `public.deleted_records` (migration 0051) — land-change patches a later scan
  replaced, so an earlier season's detections stay in the record.

The grouping is pure and tested apart from the database; build_record only
reads.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.farmland import (
    AlertSeverity,
    LonLat,
    RecordData,
    RecordEntry,
    RecordEntryKind,
    RecordEntryStatus,
    RecordRead,
)

ENCROACHMENT_MODEL = "encroachment_detector_v1"
LAND_CHANGE_MODEL = "land_change_v1"
OFFICER_STATUSES = ("acknowledged", "resolved", "dismissed")

# The daily sweep re-reads each LGA once every 12 days (REVISIT_DAYS in the
# ingestion service). A watch raised again at the next read is the same watch
# continuing; one extra day of slack absorbs a skipped or late sweep.
EPISODE_GAP_DAYS = 13

_SIGMA = re.compile(r"change ([\d.]+)σ")
_SEVERITIES = {s.value for s in AlertSeverity}


def sigma_of(zone_name: str | None) -> float | None:
    """The radar change in sigma, as the alert text states it ("… 2.0σ")."""
    m = _SIGMA.search(zone_name or "")
    return float(m.group(1)) if m else None


def _severity(value: str | None) -> AlertSeverity | None:
    return AlertSeverity(value) if value in _SEVERITIES else None


def _point(lon: float | None, lat: float | None) -> LonLat | None:
    return LonLat(lon=lon, lat=lat) if lon is not None and lat is not None else None


@dataclass(frozen=True)
class WatchRead:
    lga: str
    day: date
    severity: str
    score: float
    lon: float | None
    lat: float | None
    area_ha: int | None
    livelihoods: int | None
    zone_name: str | None


@dataclass(frozen=True)
class Patch:
    day: date
    lga: str | None
    lon: float | None
    lat: float | None


def group_watches(
    reads: list[WatchRead], active: set[tuple[str, date]],
) -> list[RecordEntry]:
    """Group daily watch reads into episodes, one per LGA per continuous run.

    An episode is ACTIVE when its latest read is the watch now on the live list
    (same LGA, raised that day); otherwise the LGA read calm at a later revisit
    and the episode ENDED.
    """
    by_lga: dict[str, list[WatchRead]] = defaultdict(list)
    for r in sorted(reads, key=lambda r: (r.lga, r.day)):
        by_lga[r.lga].append(r)
    entries: list[RecordEntry] = []
    for lga, rs in by_lga.items():
        run = [rs[0]]
        for r in rs[1:]:
            if (r.day - run[-1].day).days <= EPISODE_GAP_DAYS:
                run.append(r)
            else:
                entries.append(_episode(lga, run, active))
                run = [r]
        entries.append(_episode(lga, run, active))
    return entries


def _episode(lga: str, run: list[WatchRead], active: set[tuple[str, date]]) -> RecordEntry:
    last = run[-1]
    peak = max(run, key=lambda r: r.score)
    return RecordEntry(
        kind=RecordEntryKind.RADAR_WATCH,
        status=(RecordEntryStatus.ACTIVE if (lga, last.day) in active
                else RecordEntryStatus.ENDED),
        lga=lga,
        start=run[0].day,
        end=last.day,
        reads=[RecordRead(day=r.day, score=round(r.score, 3), sigma=sigma_of(r.zone_name))
               for r in run],
        severity=_severity(peak.severity),
        peak_score=round(peak.score, 3),
        peak_sigma=sigma_of(peak.zone_name),
        summary=peak.zone_name,
        location=_point(last.lon, last.lat),
        affected_area_ha=last.area_ha,
        livelihoods_at_risk=last.livelihoods,
    )


def group_scans(patches: list[Patch], status: RecordEntryStatus) -> list[RecordEntry]:
    """One entry per land-change scan day, carrying every patch's position."""
    by_day: dict[date, list[Patch]] = defaultdict(list)
    for p in patches:
        by_day[p.day].append(p)
    return [
        RecordEntry(
            kind=RecordEntryKind.LAND_CHANGE_SCAN,
            status=status,
            start=day,
            end=day,
            patches=len(ps),
            lgas=len({p.lga for p in ps if p.lga}),
            points=[pt for p in ps if (pt := _point(p.lon, p.lat)) is not None],
        )
        for day, ps in by_day.items()
    ]


async def _exists(session: AsyncSession, relation: str) -> bool:
    return (await session.execute(
        text("SELECT to_regclass(:r) IS NOT NULL"), {"r": relation},
    )).scalar() is True


async def build_record(
    session: AsyncSession, tenant_id: str, year: int | None,
) -> RecordData:
    """Read the tenant's retained alerts and return one year of the record.

    The session's search_path is the tenant schema (db/engine.get_session), so
    tenant tables are unqualified. The shared archive is filtered to this
    tenant's schema by value — it never returns another tenant's rows.
    """
    reads: list[WatchRead] = []
    if await _exists(session, "encroachment_watch_history"):
        reads = [
            WatchRead(lga=r[0], day=r[1], severity=r[2], score=float(r[3]), lon=r[4],
                      lat=r[5], area_ha=r[6], livelihoods=r[7], zone_name=r[8])
            for r in (await session.execute(text(
                "SELECT lga, observed_date, severity, score, lon, lat, "
                "       affected_area_ha, livelihoods_at_risk, zone_name "
                "FROM encroachment_watch_history"
            ))).all()
        ]
    active = {
        (r[0], r[1]) for r in (await session.execute(text(
            "SELECT lga, created_at::date FROM alert_events "
            "WHERE model_name = :m AND status = 'pending_review' AND is_deleted = FALSE"
        ), {"m": ENCROACHMENT_MODEL})).all()
    }
    entries = group_watches(reads, active)

    live = [
        Patch(day=r[0], lga=r[1], lat=r[2], lon=r[3])
        for r in (await session.execute(text(
            "SELECT created_at::date, lga, ST_Y(location), ST_X(location) "
            "FROM alert_events WHERE model_version = :lc "
            "AND status = 'pending_review' AND is_deleted = FALSE"
        ), {"lc": LAND_CHANGE_MODEL})).all()
    ]
    entries += group_scans(live, RecordEntryStatus.ACTIVE)

    if await _exists(session, "public.deleted_records"):
        replaced = [
            Patch(day=r[0], lga=r[1], lat=r[2], lon=r[3])
            for r in (await session.execute(text(
                "SELECT (row_data->>'created_at')::timestamptz::date, row_data->>'lga', "
                "       ST_Y((row_data->>'location')::geometry), "
                "       ST_X((row_data->>'location')::geometry) "
                "FROM public.deleted_records "
                "WHERE schema_name = :schema AND table_name = 'alert_events' "
                "AND operation = 'DELETE' AND row_data->>'model_version' = :lc"
            ), {"schema": f"tenant_{tenant_id}", "lc": LAND_CHANGE_MODEL})).all()
        ]
        entries += group_scans(replaced, RecordEntryStatus.SUPERSEDED)

    for r in (await session.execute(text(
        "SELECT lga, severity, status, zone_name, created_at::date, updated_at::date, "
        "       ST_X(location), ST_Y(location), affected_area_ha, livelihoods_at_risk "
        "FROM alert_events WHERE status IN ('acknowledged', 'resolved', 'dismissed') "
        "AND is_deleted = FALSE"
    ))).all():
        entries.append(RecordEntry(
            kind=RecordEntryKind.OFFICER_CLOSED,
            status=RecordEntryStatus(r[2]),
            lga=r[0],
            start=r[4],
            end=r[5],
            reads=[RecordRead(day=r[4], sigma=sigma_of(r[3]))],
            severity=_severity(r[1]),
            peak_sigma=sigma_of(r[3]),
            summary=r[3],
            location=_point(r[6], r[7]),
            affected_area_ha=r[8],
            livelihoods_at_risk=r[9],
        ))

    years = sorted({e.start.year for e in entries}, reverse=True)
    chosen = year if year is not None else (years[0] if years else None)
    shown = sorted(
        (e for e in entries if e.start.year == chosen),
        key=lambda e: (e.start, e.end), reverse=True,
    )
    return RecordData(
        year=chosen,
        years=years,
        watches_kept_since=min((r.day for r in reads), default=None),
        entries=shown,
    )
