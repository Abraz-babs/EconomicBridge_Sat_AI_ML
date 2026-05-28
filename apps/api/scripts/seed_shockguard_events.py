"""Seed deterministic shock_events rows for all pilot tenants (demo data).

ShockGuard (Module 05) normally ships rows from services/shock_detector.py
via the /shockguard/scan endpoint, so the table is empty until someone runs
a scan and the dashboard map starts blank. This seed writes a handful of
plausible flood + drought events per tenant at real LGA centroids so the
map, halos and timeline render without a manual scan.

Each tenant gets a spread of severities including at least one critical /
high event, alternating flood and drought, with detector-appropriate
metrics (flood: SAR backscatter delta dB; drought: LST anomaly + NDVI delta).

Idempotent: deletes prior source='seed_v1' rows before inserting. Real
detector rows (source='detector_v1' / 'sentinel1_unet_v1') are untouched.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.lga_geo import LGA_CENTROIDS, centroid_for  # noqa: E402
from services.shock_detector import (  # noqa: E402
    DETECTOR_NAME_DROUGHT,
    DETECTOR_NAME_FLOOD,
    DETECTOR_VERSION,
)
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name  # noqa: E402


SEED_SOURCE = "seed_v1"
EVENTS_PER_TENANT = 5

# severity -> (confidence_band, representative confidence).
_SEVERITY_BANDS: dict[str, tuple[str, float]] = {
    "critical": ("HIGH", 0.93),
    "high": ("HIGH", 0.88),
    "medium": ("MEDIUM", 0.78),
    "low": ("LOW", 0.62),
}
# Cycle guarantees every tenant gets a loud (critical) event for the halo
# plus a realistic spread down the severity ramp.
_SEVERITY_CYCLE: tuple[str, ...] = ("critical", "high", "medium", "high", "low")


def _hash_unit(*parts: str) -> float:
    """Deterministic [0, 1) draw from the joined parts."""
    h = hashlib.md5("|".join(parts).encode(), usedforsecurity=False).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class ShockSeed:
    event_type: str
    detector_name: str
    severity: str
    confidence: float
    confidence_band: str
    projected_onset_hours: int
    affected_area_km2: float
    population_at_risk: int
    lga: str
    lon: float
    lat: float
    metrics: dict[str, float]


def _metrics_for(tenant_id: str, lga: str, is_flood: bool) -> dict[str, float]:
    """Detector-specific metric payload for the JSONB column."""
    if is_flood:
        return {
            "backscatter_delta_db": -round(3 + _hash_unit(tenant_id, lga, "bs") * 9, 2),
        }
    return {
        "lst_anomaly_c": round(2 + _hash_unit(tenant_id, lga, "lst") * 6, 2),
        "ndvi_anomaly": -round(0.10 + _hash_unit(tenant_id, lga, "ndvi") * 0.40, 3),
    }


def _rows_for(tenant_id: str) -> list[ShockSeed]:
    lgas = list(LGA_CENTROIDS.get(tenant_id, {}).keys())[:EVENTS_PER_TENANT]
    rows: list[ShockSeed] = []
    for i, lga in enumerate(lgas):
        lon, lat = centroid_for(tenant_id, lga)
        is_flood = i % 2 == 0
        severity = _SEVERITY_CYCLE[i % len(_SEVERITY_CYCLE)]
        band, conf = _SEVERITY_BANDS[severity]
        rows.append(ShockSeed(
            event_type="flood" if is_flood else "drought",
            detector_name=DETECTOR_NAME_FLOOD if is_flood else DETECTOR_NAME_DROUGHT,
            severity=severity,
            confidence=conf,
            confidence_band=band,
            projected_onset_hours=6 + int(_hash_unit(tenant_id, lga, "onset") * 60),
            affected_area_km2=round(40 + _hash_unit(tenant_id, lga, "area") * 760, 1),
            population_at_risk=int(3_000 + _hash_unit(tenant_id, lga, "pop") * 140_000),
            lga=lga,
            lon=lon,
            lat=lat,
            metrics=_metrics_for(tenant_id, lga, is_flood),
        ))
    return rows


_INSERT_SQL = text(
    """
    INSERT INTO shock_events (
        tenant_id, event_type, detector_name, detector_version,
        severity, confidence, confidence_band, requires_human_review,
        projected_onset_hours, affected_area_km2, population_at_risk,
        location, lga, zone_name, metrics, source
    ) VALUES (
        :tenant_id, :event_type, :detector_name, :detector_version,
        :severity, :confidence, :confidence_band, :requires_human_review,
        :onset, :area, :pop,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        :lga, :zone_name, CAST(:metrics AS JSONB), :source
    )
    """
)


async def seed() -> int:
    factory = get_session_factory()
    total = 0
    async with factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            await session.execute(
                text("DELETE FROM shock_events WHERE source = :src"),
                {"src": SEED_SOURCE},
            )
            for r in _rows_for(tenant_id):
                await session.execute(
                    _INSERT_SQL,
                    {
                        "tenant_id": tenant_id,
                        "event_type": r.event_type,
                        "detector_name": r.detector_name,
                        "detector_version": DETECTOR_VERSION,
                        "severity": r.severity,
                        "confidence": r.confidence,
                        "confidence_band": r.confidence_band,
                        "requires_human_review": r.confidence_band != "HIGH",
                        "onset": r.projected_onset_hours,
                        "area": r.affected_area_km2,
                        "pop": r.population_at_risk,
                        "lon": r.lon,
                        "lat": r.lat,
                        "lga": r.lga,
                        "zone_name": r.lga,
                        "metrics": json.dumps(r.metrics),
                        "source": SEED_SOURCE,
                    },
                )
                total += 1
        await session.commit()
    return total


async def main() -> None:
    n = await seed()
    print(f"seeded {n} shock_events rows (source={SEED_SOURCE})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
