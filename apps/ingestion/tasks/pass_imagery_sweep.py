"""Pass-driven CDSE refresh — wake imagery search around N2YO passes.

Today the dashboard's freshness indicator only updates when a user
loads the page (the 10-min TTL cache expires lazily). That's fine for
"good enough" recency, but it means the cache is usually populated by
imagery that was generated *between* passes, not by what just landed.

This sweeper closes the loop:

  every 15 minutes:
    for each pilot tenant:
      for each EO satellite (Sentinel-1 / Sentinel-2):
        ask N2YO when the next pass is
        if a pass starts within ±PASS_WINDOW_MIN of now:
            call services.imagery_recent.get_recent_imagery() — which
            warms the cache for the dashboard

The sweeper makes no DB writes. It exists solely to pre-warm the
imagery cache so the next dashboard load gets fresh data without
paying a CDSE round-trip on the read path.

N2YO quota: 10 tenants × 4 satellites = 40 transactions per sweep.
At one sweep per 15 min that's 160/h — well under the 1000/h free
tier limit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from db import PILOT_TENANT_IDS
from services.imagery_recent import get_recent_imagery
from sources.copernicus import CopernicusError
from sources.n2yo import (
    SATELLITE_CATALOG,
    N2yoClient,
    N2yoError,
    SatellitePass,
)
from sources.nasa_firms import PILOT_BBOX


log = logging.getLogger(__name__)


# Satellites that produce STAC-searchable imagery. VIIRS/MODIS heat data
# arrives via NASA FIRMS, not CDSE STAC — those satellites are excluded
# from this sweep on purpose.
EO_SATELLITES: tuple[str, ...] = (
    "SENTINEL-1A",
    "SENTINEL-1C",
    "SENTINEL-2A",
    "SENTINEL-2B",
)

# A predicted pass within ±this many minutes of `now` counts as "near"
# and triggers a refresh. 20 min spans one whole sweep period either
# side, so any pass during a sweep window is caught by at least one
# sweep run.
PASS_WINDOW_MIN: int = 20

# Minimum peak elevation for the N2YO query. Lower than the dashboard's
# default (30°) because we still want a refresh for grazing passes that
# *might* produce a partial scene.
SWEEP_MIN_ELEVATION: int = 15

# N2YO look-ahead: 1 day is plenty since we only care about passes
# within the next 20 min. Saves transactions vs. the default 2.
SWEEP_DAYS: int = 1


GROUP_TO_COLLECTION: dict[str, str] = {
    "S1": "sentinel-1-grd",
    "S2": "sentinel-2-l2a",
}


@dataclass(frozen=True, slots=True)
class SweepDecision:
    """Why a (tenant, satellite) pair did or did not refresh."""

    tenant_id: str
    satellite: str
    collection: str | None
    minutes_to_pass: int | None  # negative = past
    refreshed: bool
    skipped_reason: str | None  # "no pass in window", "n2yo error", ...
    error: str | None = None


@dataclass
class SweepResult:
    """Top-level summary returned to scheduler logs."""

    ran_at: datetime
    decisions: list[SweepDecision] = field(default_factory=list)

    @property
    def refreshed_count(self) -> int:
        return sum(1 for d in self.decisions if d.refreshed)

    @property
    def skipped_count(self) -> int:
        return len(self.decisions) - self.refreshed_count


# ─── Sweep ────────────────────────────────────────────────────────────────


async def run_pass_imagery_sweep(
    *,
    tenants: list[str] | None = None,
    n2yo: N2yoClient | None = None,
    now: datetime | None = None,
) -> SweepResult:
    """Run one sweep tick across the given tenants.

    Args:
        tenants: Override the tenant list (tests). Defaults to all
            PILOT_TENANT_IDS that have an entry in PILOT_BBOX.
        n2yo: Inject a pre-built N2yoClient for tests.
        now: Override "current time" (tests / freezegun-free unit tests).

    Returns:
        SweepResult with one SweepDecision per (tenant, satellite). A
        failure on one pair never short-circuits the rest.
    """
    when = now if now is not None else datetime.now(timezone.utc)
    target_tenants = (
        list(tenants)
        if tenants is not None
        else sorted(PILOT_TENANT_IDS & PILOT_BBOX.keys())
    )
    client = n2yo if n2yo is not None else N2yoClient()
    result = SweepResult(ran_at=when)

    for tenant_id in target_tenants:
        if tenant_id not in PILOT_BBOX:
            continue
        lat, lon = _centroid_for(tenant_id)
        for sat in EO_SATELLITES:
            decision = await _decide_and_refresh(
                tenant_id=tenant_id,
                satellite=sat,
                lat=lat,
                lon=lon,
                client=client,
                now=when,
            )
            result.decisions.append(decision)

    log.info(
        "pass_imagery_sweep ran_at=%s refreshed=%d skipped=%d",
        when.isoformat(), result.refreshed_count, result.skipped_count,
    )
    return result


# ─── Per-pair decision ────────────────────────────────────────────────────


async def _decide_and_refresh(
    *,
    tenant_id: str,
    satellite: str,
    lat: float,
    lon: float,
    client: N2yoClient,
    now: datetime,
) -> SweepDecision:
    _, group = SATELLITE_CATALOG[satellite]
    collection = GROUP_TO_COLLECTION.get(group)
    if collection is None:
        # Defensive — shouldn't happen because EO_SATELLITES only lists S1/S2,
        # but if someone adds a non-EO satellite to that tuple the sweep
        # should report-and-skip rather than crash.
        return SweepDecision(
            tenant_id=tenant_id,
            satellite=satellite,
            collection=None,
            minutes_to_pass=None,
            refreshed=False,
            skipped_reason="no-stac-collection",
        )

    try:
        passes = await client.fetch_passes(
            satellite_key=satellite,
            observer_lat=lat,
            observer_lon=lon,
            days=SWEEP_DAYS,
            min_elevation=SWEEP_MIN_ELEVATION,
        )
    except (N2yoError, ValueError) as exc:
        return SweepDecision(
            tenant_id=tenant_id,
            satellite=satellite,
            collection=collection,
            minutes_to_pass=None,
            refreshed=False,
            skipped_reason="n2yo-error",
            error=str(exc),
        )

    nearby = _pick_pass_in_window(passes, now=now, window_min=PASS_WINDOW_MIN)
    if nearby is None:
        return SweepDecision(
            tenant_id=tenant_id,
            satellite=satellite,
            collection=collection,
            minutes_to_pass=_minutes_to_next(passes, now=now),
            refreshed=False,
            skipped_reason="no-pass-in-window",
        )

    minutes = _minutes_diff(nearby.start_utc, now)
    try:
        await get_recent_imagery(
            tenant_id=tenant_id,
            collection=collection,
            days=14,
            limit=10,
        )
    except (CopernicusError, ValueError) as exc:
        return SweepDecision(
            tenant_id=tenant_id,
            satellite=satellite,
            collection=collection,
            minutes_to_pass=minutes,
            refreshed=False,
            skipped_reason="cdse-error",
            error=str(exc),
        )

    return SweepDecision(
        tenant_id=tenant_id,
        satellite=satellite,
        collection=collection,
        minutes_to_pass=minutes,
        refreshed=True,
        skipped_reason=None,
    )


# ─── Pure helpers ─────────────────────────────────────────────────────────


def _centroid_for(tenant_id: str) -> tuple[float, float]:
    w, s, e, n = PILOT_BBOX[tenant_id]
    return ((s + n) / 2.0, (w + e) / 2.0)


def _pick_pass_in_window(
    passes: list[SatellitePass],
    *,
    now: datetime,
    window_min: int,
) -> SatellitePass | None:
    """Return the earliest pass with |start - now| <= window_min, else None.

    N2YO only returns FUTURE passes — so this effectively asks "is the
    next pass within the next `window_min` minutes?" The lower-bound is
    here for clarity (and to be robust if we ever feed in cached past
    passes from another source)."""
    if not passes:
        return None
    sorted_passes = sorted(passes, key=lambda p: p.start_utc)
    for p in sorted_passes:
        if abs(_minutes_diff(p.start_utc, now)) <= window_min:
            return p
    return None


def _minutes_to_next(
    passes: list[SatellitePass], *, now: datetime
) -> int | None:
    """Minutes until the next future pass (positive), or None if none."""
    future = [p for p in passes if p.start_utc > now]
    if not future:
        return None
    next_p = min(future, key=lambda p: p.start_utc)
    return _minutes_diff(next_p.start_utc, now)


def _minutes_diff(instant: datetime, now: datetime) -> int:
    """Signed minutes between `instant` and `now`. Negative = past."""
    return int((instant - now).total_seconds() // 60)
