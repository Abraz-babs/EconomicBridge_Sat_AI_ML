"""Field directions — the named village nearest an alert's coordinates.

Satellites give coordinates; a field team needs a place to drive to. Every
alert is paired with the nearest village in public.named_settlements (GRID3
settlement names, CC BY 4.0 — migration 0052), with its ward, the distance,
and the compass direction FROM the village TO the alert, because that is how a
team walks it: reach Kurmin Kaya, then head 1.0 km south-east.

Looked up at read time, one batched query per response, so every alert —
live, past or yet to come — carries it with no change to the detectors. If the
table is missing or empty, alerts simply come back without it.
"""
from __future__ import annotations

import logging
import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.farmland import LonLat, NearestPlace

log = logging.getLogger(__name__)

# Closer than this, the alert is AT the village — no direction to give.
AT_PLACE_KM = 0.15
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(from_lon: float, from_lat: float, to_lon: float, to_lat: float) -> str:
    """Eight-point compass direction of travel from one point to another."""
    p1, p2 = math.radians(from_lat), math.radians(to_lat)
    dl = math.radians(to_lon - from_lon)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return _COMPASS[round(deg / 45) % 8]


async def nearest_places(
    session: AsyncSession, points: list[tuple[float, float] | None],
) -> list[NearestPlace | None]:
    """The nearest named village for each (lon, lat); None where unknown."""
    out: list[NearestPlace | None] = [None] * len(points)
    wanted = [(i, p) for i, p in enumerate(points) if p is not None]
    if not wanted:
        return out
    try:
        async with session.begin_nested():
            if not (await session.execute(
                text("SELECT to_regclass('public.named_settlements') IS NOT NULL"),
            )).scalar():
                return out
            rows = (await session.execute(text("""
                SELECT t.i, s.name, s.ward, s.lga, ST_X(s.geom), ST_Y(s.geom),
                       ST_Distance(s.geom::geography,
                                   ST_SetSRID(ST_MakePoint(t.lon, t.lat), 4326)::geography)
                FROM unnest(CAST(:i AS int[]), CAST(:lon AS float8[]), CAST(:lat AS float8[]))
                     AS t(i, lon, lat)
                CROSS JOIN LATERAL (
                    SELECT name, ward, lga, geom FROM public.named_settlements
                    ORDER BY geom <-> ST_SetSRID(ST_MakePoint(t.lon, t.lat), 4326)
                    LIMIT 1
                ) s
            """), {
                "i": [i for i, _ in wanted],
                "lon": [p[0] for _, p in wanted],
                "lat": [p[1] for _, p in wanted],
            })).all()
    except Exception as exc:  # noqa: BLE001 — directions are extra; never fail the alerts
        log.warning("nearest_places lookup failed: %r", exc)
        return out
    for i, name, ward, lga, v_lon, v_lat, metres in rows:
        lon, lat = points[i]  # type: ignore[misc]
        km = metres / 1000
        out[i] = NearestPlace(
            name=name, ward=ward, lga=lga, distance_km=round(km, 1),
            direction=None if km < AT_PLACE_KM else compass(v_lon, v_lat, lon, lat),
            location=LonLat(lon=v_lon, lat=v_lat),
        )
    return out
