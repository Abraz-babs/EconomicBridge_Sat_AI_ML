"""Government-agency email alert digests.

For each active `public.agency_alert_subscriptions` row, find the NEW alerts
(since `last_notified_at`) for that tenant + module at/above the agency's
severity threshold, and email an English digest. Module → duty:
  * shockguard → disaster agencies (NEMA / SEMA): flood / drought
  * farmland   → security / agriculture: encroachment & land-disturbance
  * cropguard  → agriculture: crop stress (poor / stressed NDVI)

SMS is a separate, deferred channel — this is email-only (via services.email).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from schemas.places import NearestPlace
from services.data_source import NOT_SYNTHETIC
from services.email import send_alert_email
from services.places import nearest_places
from services.tenants import tenant_schema_name

log = logging.getLogger(__name__)

_SEV_RANK = {"all": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_MODULE_LABEL = {
    "farmland": "Farmland encroachment",
    "shockguard": "ShockGuard radar signals",
    "cropguard": "CropGuard crop-stress",
}
_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class AlertLine:
    severity: str
    lga: str | None
    detail: str
    when: datetime
    # Field directions for a real point: nearest village, ward, and a link a
    # team can open on a phone. None for area-level lines (crop health).
    where: str | None = None


def directions(place: NearestPlace | None, lon: float, lat: float) -> str | None:
    """'4.4 km NE of Mahuta, Kyangakwai ward — directions: <maps link>'."""
    if place is None:
        return None
    at = (f"{place.distance_km:.1f} km {place.direction} of {place.name}"
          if place.direction else f"at {place.name}")
    ward = f", {place.ward} ward" if place.ward and place.ward != place.name else ""
    return (f"{at}{ward} — directions: "
            f"https://www.google.com/maps/dir/?api=1&destination={lat:.5f},{lon:.5f}")


async def _with_directions(
    session: AsyncSession, rows: list[dict], make: Callable[[dict], AlertLine],
) -> list[AlertLine]:
    """Build the lines, then attach each one's village in a single lookup."""
    points = [(float(r["lon"]), float(r["lat"])) if r.get("lon") is not None
              and r.get("lat") is not None else None for r in rows]
    places = await nearest_places(session, points)
    out: list[AlertLine] = []
    for r, pt, place in zip(rows, points, places):
        ln = make(r)
        where = directions(place, *pt) if pt else None
        out.append(AlertLine(ln.severity, ln.lga, ln.detail, ln.when, where))
    return out


async def _farmland_lines(session: AsyncSession, since: datetime, min_rank: int) -> list[AlertLine]:
    rows = (await session.execute(text(
        "SELECT severity, lga, zone_name, created_at, "
        "       ST_X(location) AS lon, ST_Y(location) AS lat FROM alert_events "
        "WHERE model_name = 'encroachment_detector_v1' AND NOT is_deleted "
        "AND created_at > :since ORDER BY created_at DESC LIMIT 100"
    ), {"since": since})).mappings().all()
    kept = [dict(r) for r in rows if _SEV_RANK.get(r["severity"], 0) >= min_rank]
    return await _with_directions(session, kept, lambda r: AlertLine(
        r["severity"], r["lga"], r["zone_name"] or "land-disturbance watch", r["created_at"]))


async def _shockguard_lines(session: AsyncSession, since: datetime, min_rank: int) -> list[AlertLine]:
    # Live satellite detections only — their point is the measured box, so
    # directions to it are real (schemas/places.py).
    rows = (await session.execute(text(
        "SELECT severity, lga, event_type, zone_name, created_at, "
        "       ST_X(location) AS lon, ST_Y(location) AS lat FROM shock_events "
        f"WHERE source = 'shockguard_scan_v1' AND {NOT_SYNTHETIC} AND created_at > :since "
        "ORDER BY created_at DESC LIMIT 100"
    ), {"since": since})).mappings().all()
    kept = [dict(r) for r in rows if _SEV_RANK.get(r["severity"], 0) >= min_rank]
    return await _with_directions(session, kept, lambda r: AlertLine(
        r["severity"], r["lga"],
        f"{'surface water (radar, unconfirmed)' if r['event_type'] == 'flood' else r['event_type']}"
        f" — {r['zone_name'] or ''}".strip(" —"), r["created_at"]))


async def _cropguard_lines(session: AsyncSession, since: datetime, min_rank: int) -> list[AlertLine]:
    # crop_health has no severity column — map health → severity rank.
    rank = {"poor": 3, "stressed": 2}
    rows = (await session.execute(text(
        "SELECT lga, health, ndvi, created_at FROM crop_health "
        "WHERE health IN ('poor', 'stressed') AND created_at > :since "
        "ORDER BY created_at DESC LIMIT 200"
    ), {"since": since})).mappings().all()
    out: list[AlertLine] = []
    for r in rows:
        if rank.get(r["health"], 0) < min_rank:
            continue
        sev = "high" if r["health"] == "poor" else "medium"
        ndvi = f" (NDVI {r['ndvi']:.2f})" if r["ndvi"] is not None else ""
        out.append(AlertLine(sev, r["lga"], f"crop {r['health']}{ndvi}", r["created_at"]))
    return out


_FETCHERS = {
    "farmland": _farmland_lines,
    "shockguard": _shockguard_lines,
    "cropguard": _cropguard_lines,
}


def _render(agency: str, tenant_id: str, module: str, lines: list[AlertLine], since: datetime) -> tuple[str, str]:
    n = len(lines)
    label = _MODULE_LABEL.get(module, module)
    state = tenant_id.replace("_", " ").title()
    subject = f"[EconomicBridge] {n} new {label} alert(s) — {state}"
    url = getattr(get_settings(), "public_app_url", None) or "https://economicbridge.app/dashboard"
    body = [
        f"Dear {agency},",
        "",
        f"EconomicBridge has detected {n} new {label} alert(s) relevant to your "
        f"operations in {state} since {since:%Y-%m-%d %H:%M UTC}:",
        "",
    ]
    for ln in lines[:25]:
        body.append(f"  - {ln.severity.upper()} - {ln.lga or '-'} - {ln.detail} - {ln.when:%Y-%m-%d}")
        if ln.where:
            body.append(f"      {ln.where}")
    if n > 25:
        body.append(f"  ...and {n - 25} more.")
    body += [
        "",
        f"View the live map and details: {url}",
        "",
        "These are model-derived indicators from live Sentinel-2 / Sentinel-1 / "
        "NASA satellite data; human verification is advised before field action.",
        *(["Village names: GRID3, CC BY 4.0."] if any(ln.where for ln in lines) else []),
        "",
        "- EconomicBridge (operated by Bizra Farms Integrated Nigeria Ltd)",
    ]
    return subject, "\n".join(body)


async def send_agency_digests(
    session: AsyncSession, *, only_id=None, force: bool = False,
) -> list[dict]:
    """Send each active agency its new relevant alerts. `force` sends even when
    there are no new alerts (useful for a demo / test). Returns per-subscription
    outcomes. Caller owns the session."""
    where = "WHERE is_active = TRUE"
    params: dict[str, object] = {}
    if only_id is not None:
        where += " AND id = :id"
        params["id"] = only_id
    await session.execute(text("SET search_path TO public"))
    subs = (await session.execute(text(
        "SELECT id, agency_name, recipient_email, tenant_id, module, "
        "severity_threshold, last_notified_at "
        f"FROM public.agency_alert_subscriptions {where}"
    ), params)).mappings().all()

    out: list[dict] = []
    for sub in subs:
        since = sub["last_notified_at"] or _EPOCH
        min_rank = _SEV_RANK.get(sub["severity_threshold"], 3)
        try:
            await session.execute(text(
                f"SET search_path TO {tenant_schema_name(sub['tenant_id'])}, public"))
            lines = await _FETCHERS[sub["module"]](session, since, min_rank)
        except Exception as exc:  # noqa: BLE001 — one bad subscription never blocks the rest
            log.warning("agency digest fetch failed sub=%s: %s", sub["id"], exc)
            lines = []

        sent = False
        if lines or force:
            subject, body = _render(sub["agency_name"], sub["tenant_id"], sub["module"], lines, since)
            sent = send_alert_email(to=sub["recipient_email"], subject=subject, body=body)
            await session.execute(text("SET search_path TO public"))
            await session.execute(text(
                "UPDATE public.agency_alert_subscriptions "
                "SET last_notified_at = NOW() WHERE id = :id"
            ), {"id": sub["id"]})
            await session.commit()

        out.append({
            "subscription_id": str(sub["id"]),
            "agency": sub["agency_name"],
            "tenant_id": sub["tenant_id"],
            "module": sub["module"],
            "new_alerts": len(lines),
            "emailed": sent,
        })
    await session.execute(text("SET search_path TO public"))
    log.info("agency digests: %s", out)
    return out
