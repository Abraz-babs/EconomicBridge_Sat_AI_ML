"""Business-logic layer for the Farmland Protection module.

Orchestrates repositories and applies the rules routers shouldn't know about:
soft-delete handling, default sort, ORM → Pydantic mapping (including the
PostGIS POINT → {lon, lat} unwrap).

Routers call the functions here; nothing here touches HTTP.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_event import AlertEvent
from repositories import alerts as alerts_repo
from schemas.farmland import AlertListQuery, AlertResponse, AlertStatus, LonLat


def _point_to_lonlat(value: object | None) -> LonLat | None:
    """Convert a GeoAlchemy2 WKBElement or WKT string POINT to {lon, lat}.

    GeoAlchemy2 returns geometry as a `WKBElement`; converting it inline (rather
    than asking Postgres to ST_AsGeoJSON) avoids an extra round-trip per row.
    """
    if value is None:
        return None

    # Local imports to keep the hot path light and skip if geoalchemy is missing
    # at import time (defensive — it's a real dependency).
    try:
        from geoalchemy2.shape import to_shape
    except ImportError:  # pragma: no cover
        return None

    try:
        shape = to_shape(value)  # type: ignore[arg-type]
    except (TypeError, AttributeError):
        return None

    # Shapely point: shape.x = longitude, shape.y = latitude
    return LonLat(lon=float(shape.x), lat=float(shape.y))


def alert_to_response(row: AlertEvent) -> AlertResponse:
    """Map an AlertEvent ORM row to its public schema representation."""
    return AlertResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        alert_type=row.alert_type,        # type: ignore[arg-type]  # enum validator handles
        severity=row.severity,             # type: ignore[arg-type]
        status=row.status,                 # type: ignore[arg-type]
        zone_name=row.zone_name,
        lga=row.lga,
        location=_point_to_lonlat(row.location),
        confidence_score=row.confidence_score,
        affected_area_ha=row.affected_area_ha,
        livelihoods_at_risk=row.livelihoods_at_risk,
        economic_value_ngn=row.economic_value_ngn,
        predicted_breach_hours=row.predicted_breach_hours,
        satellite_source=row.satellite_source,
        satellite_pass_time=row.satellite_pass_time,
        model_name=row.model_name,
        model_version=row.model_version,
        human_review_required=row.human_review_required,
        agencies_notified=row.agencies_notified,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_alerts(
    session: AsyncSession, query: AlertListQuery
) -> tuple[list[AlertResponse], int]:
    """Return (responses, total) for the requested filter window."""
    rows, total = await alerts_repo.list_alerts(session, query)
    return [alert_to_response(r) for r in rows], total


async def update_alert_status(
    session: AsyncSession, alert_id: UUID, new_status: AlertStatus
) -> AlertResponse | None:
    """Transition an alert's status (e.g. pending_review -> resolved).

    Returns None if no row matches `alert_id` in the active tenant schema.
    """
    row = await alerts_repo.get_by_id(session, alert_id)
    if row is None or row.is_deleted:
        return None
    updated = await alerts_repo.update_status(session, row, new_status)
    return alert_to_response(updated)
