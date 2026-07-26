"""Load DOCUMENTED historical shock events into tenant_<id>.shock_events.

Replaces the invented fixtures written by scripts/seed_shockguard_events.py.
The ShockGuard panel labels non-live rows HISTORICAL; until now those rows were
synthetic "plausible" events, so the label implied something untrue. Every row
this script writes is a real, recorded disaster with a citable source — see
scripts/historical_shocks_data.py for the dataset and the rules for adding to it.

What it writes, per event:
  * one row per named LGA (so the map pins where it actually happened), or a
    single statewide row when the source published no LGA breakdown;
  * source='historical_v1' — distinct from the live scan ('shockguard_scan_v1')
    and from the old fixtures ('seed_v1');
  * created_at = the DATE THE EVENT HAPPENED, not the load time, so the feed
    orders correctly and "46 days ago" style ages are truthful;
  * provenance (source name + URL + reported figures) in the metrics JSONB.

Idempotent: deletes prior source='historical_v1' rows per tenant, then inserts.
Also clears the legacy 'seed_v1' fixtures it supersedes. Live detector rows
('detector_v1', 'shockguard_scan_v1', 'sentinel1_unet_v1') are never touched.

Run:  python -m scripts.load_historical_shocks
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_session_factory  # noqa: E402
from scripts.historical_shocks_data import (  # noqa: E402
    HISTORICAL_EVENTS,
    TENANTS_AWAITING_RESEARCH,
    HistoricalShock,
)
from services.lga_geo import centroid_for  # noqa: E402
from services.tenants import tenant_schema_name  # noqa: E402

HISTORICAL_SOURCE = "historical_v1"
LEGACY_FIXTURE_SOURCE = "seed_v1"
DETECTOR_NAME = "historical_record"
DETECTOR_VERSION = "1.0.0"

# A documented event is not a prediction: confidence is certainty that it
# happened (it did — it is in the record), onset lead time is meaningless, and
# nothing needs an analyst to review it.
_CONFIDENCE = 1.0
_CONFIDENCE_BAND = "HIGH"

_INSERT_SQL = text(
    """
    INSERT INTO shock_events (
        tenant_id, event_type, detector_name, detector_version,
        severity, confidence, confidence_band, requires_human_review,
        projected_onset_hours, affected_area_km2, population_at_risk,
        location, lga, zone_name, metrics, source, created_at
    ) VALUES (
        :tenant_id, :event_type, :detector_name, :detector_version,
        :severity, :confidence, :confidence_band, FALSE,
        0, 0, :pop,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        :lga, :zone_name, CAST(:metrics AS JSONB), :source, :created_at
    )
    """
)


def _event_timestamp(shock: HistoricalShock) -> datetime:
    """Midday UTC on the event date — a date with no clock time would sort
    against midnight and read as the previous day in western time zones."""
    return datetime.combine(shock.event_date, time(12, 0), tzinfo=timezone.utc)


def _population_share(shock: HistoricalShock, n_rows: int) -> int:
    """Split a reported people-affected total across the rows we write.

    The source reports one figure for the whole event; showing that full number
    against each LGA would multiply the impact n times over. Dividing is not
    precise per-LGA truth either, so `people_affected` in metrics always keeps
    the event-level figure the source actually published.
    """
    if not shock.people_affected or n_rows <= 0:
        return 0
    return int(shock.people_affected / n_rows)


def _rows_for(tenant_id: str, shock: HistoricalShock) -> list[dict[str, object]]:
    """Expand one event into its per-LGA (or single statewide) DB rows."""
    targets: list[str | None]
    if shock.lgas and shock.lga_breakdown_published:
        targets = list(shock.lgas)
    else:
        targets = [None]          # statewide — no invented LGA attribution

    metrics = shock.as_metrics()
    pop = _population_share(shock, len(targets))
    rows: list[dict[str, object]] = []
    for lga in targets:
        # Statewide rows carry no geometry on purpose — routers/shockguard.py
        # `_event_row` fills the tenant's representative point for display, so
        # the map still shows the state without us inventing an LGA. A NAMED
        # LGA must resolve: centroid_for raises on an unknown name, and that
        # should stop the load rather than silently drop the event.
        lon = lat = None
        if lga is not None:
            lon, lat = centroid_for(tenant_id, lga)
        rows.append({
            "tenant_id": tenant_id,
            "event_type": shock.event_type,
            "detector_name": DETECTOR_NAME,
            "detector_version": DETECTOR_VERSION,
            "severity": shock.severity,
            "confidence": _CONFIDENCE,
            "confidence_band": _CONFIDENCE_BAND,
            "pop": pop,
            "lon": lon,
            "lat": lat,
            "lga": lga,
            "zone_name": shock.title,
            "metrics": json.dumps(metrics),
            "source": HISTORICAL_SOURCE,
            "created_at": _event_timestamp(shock),
        })
    return rows


async def load() -> tuple[int, int]:
    """Write every documented event. Returns (rows_written, tenants_touched)."""
    factory = get_session_factory()
    written = 0
    tenants = 0
    async with factory() as session:
        for tenant_id, shocks in sorted(HISTORICAL_EVENTS.items()):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            # Idempotent reload + retire the invented fixtures this supersedes.
            await session.execute(
                text("DELETE FROM shock_events WHERE source IN (:hist, :legacy)"),
                {"hist": HISTORICAL_SOURCE, "legacy": LEGACY_FIXTURE_SOURCE},
            )
            for shock in shocks:
                for row in _rows_for(tenant_id, shock):
                    await session.execute(_INSERT_SQL, row)
                    written += 1
            tenants += 1
        await session.commit()
    return written, tenants


async def main() -> None:
    written, tenants = await load()
    print(f"loaded {written} documented historical rows across {tenants} tenants")
    if TENANTS_AWAITING_RESEARCH:
        print(
            "awaiting a sourced event (intentionally empty): "
            + ", ".join(TENANTS_AWAITING_RESEARCH)
        )


if __name__ == "__main__":
    asyncio.run(main())
