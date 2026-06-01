"""Unified intelligence feed — cross-tenant activity stream for the
Overview dashboard.

Aggregates the most-recent rows from every signal-producing table that
ships with the platform:

  alert_events       — FIRMS-driven heat / encroachment / conflict alerts
  ndvi_anomalies     — pre-symptomatic disease detections (Module 04)
  shock_events       — flood + drought scans (Module 05)
  aid_coverage       — recent agency × LGA upserts (Module 02)
  poverty_villages   — newly-identified poverty rows (Module 01)

Normalizes each into a FeedEvent (kind, tenant_id, title, tag, severity,
source, observed_at) so the frontend renders a single list with the
same visual language the v0.3 prototype had for hardcoded mock items.

Cross-tenant by design — the Overview tab is the "platform-wide
intelligence" view. Per-tenant filtering lives in the per-module
panels. Schema names are interpolated from the PILOT_TENANT_IDS
allowlist (services/tenants.py); never from request input.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tenants import PILOT_TENANT_IDS, tenant_schema_name

log = logging.getLogger(__name__)


FeedKind = Literal[
    "alert_event", "ndvi_anomaly", "shock_event",
    "aid_coverage", "poverty_village",
]
FeedTag = Literal["Disaster", "Agriculture", "Poverty", "Aid", "Encroachment"]
FeedSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class FeedEvent:
    """One row in the unified intelligence feed."""

    kind: FeedKind
    tenant_id: str
    title: str
    region: str | None        # LGA / settlement / agency, when known
    tag: FeedTag
    severity: FeedSeverity
    source: str               # provenance string from the originating table
    observed_at: datetime     # tz-aware UTC


# Lookback window — feed always returns rows from the trailing 90 days.
# Older activity is in the per-module audit logs; the Overview is "what's
# happening recently."
FEED_LOOKBACK_DAYS: int = 90


async def gather_feed(
    session: AsyncSession,
    *,
    limit: int = 20,
    tenants: Iterable[str] | None = None,
) -> list[FeedEvent]:
    """Return the top `limit` most-recent FeedEvents across all tenants.

    Args:
        session: Active AsyncSession. Caller does NOT need to set
            search_path — we use fully-qualified schema names.
        limit: Max events returned. 20 fits the Overview-tab scroll
            cleanly. Cap is enforced at the API router layer.
        tenants: Optional subset of pilot tenants to walk. Default = all.

    Returns:
        FeedEvents sorted observed_at DESC.
    """
    targets = set(tenants) if tenants else set(PILOT_TENANT_IDS)
    targets &= PILOT_TENANT_IDS                          # paranoia
    if not targets:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=FEED_LOOKBACK_DAYS)

    # Collect each tenant's events (recency-sorted) separately, then
    # round-robin interleave so the Overview feed MIXES regions — some
    # Nigerian states + Ghana + Senegal — instead of letting whichever
    # tenant has the freshest rows monopolise the top of the list.
    by_tenant: dict[str, list[FeedEvent]] = {}
    for tenant_id in sorted(targets):
        schema = tenant_schema_name(tenant_id)
        rows = await _gather_tenant_rows(session, schema=schema, cutoff=cutoff)
        evs = [
            ev
            for row in rows
            if (ev := _row_to_feed_event(tenant_id, row)) is not None
        ]
        evs.sort(key=lambda e: e.observed_at, reverse=True)
        if evs:
            by_tenant[tenant_id] = evs

    # Rotate which region leads by day-of-year so the mix re-orders over time
    # (the "feed shouldn't look identical every visit" ask) without RNG.
    order = sorted(by_tenant)
    if order:
        shift = datetime.now(timezone.utc).timetuple().tm_yday % len(order)
        order = order[shift:] + order[:shift]

    mixed: list[FeedEvent] = []
    depth = 0
    while len(mixed) < limit:
        progressed = False
        for tenant_id in order:
            pool = by_tenant[tenant_id]
            if depth < len(pool):
                mixed.append(pool[depth])
                progressed = True
                if len(mixed) >= limit:
                    break
        if not progressed:
            break
        depth += 1
    return mixed[:limit]


async def _gather_tenant_rows(
    session: AsyncSession, *, schema: str, cutoff: datetime,
) -> list[dict]:
    """One UNION ALL per tenant, normalized into a generic row shape."""
    sql = f"""
        SELECT 'alert_event' AS kind,
               COALESCE(alert_type, 'unknown') AS subtype,
               severity::text AS severity,
               COALESCE(lga, '') AS region,
               COALESCE(satellite_source, model_name, 'unknown') AS source,
               COALESCE(satellite_pass_time, created_at) AS observed_at,
               affected_area_ha AS metric_value,
               '' AS extra
          FROM "{schema}".alert_events
         WHERE COALESCE(satellite_pass_time, created_at) >= :cutoff
           AND is_deleted = FALSE

        UNION ALL

        SELECT 'ndvi_anomaly' AS kind,
               CASE WHEN anomaly THEN 'anomaly' ELSE 'clean' END AS subtype,
               confidence_band::text AS severity,
               COALESCE(crop, '') AS region,
               detector_name AS source,
               COALESCE(window_end::timestamptz, created_at) AS observed_at,
               z_score AS metric_value,
               '' AS extra
          FROM "{schema}".ndvi_anomalies
         WHERE created_at >= :cutoff

        UNION ALL

        SELECT 'shock_event' AS kind,
               event_type AS subtype,
               severity::text AS severity,
               COALESCE(lga, zone_name, '') AS region,
               source AS source,
               created_at AS observed_at,
               affected_area_km2 AS metric_value,
               '' AS extra
          FROM "{schema}".shock_events
         WHERE created_at >= :cutoff

        UNION ALL

        SELECT 'aid_coverage' AS kind,
               agency_slug AS subtype,
               'low' AS severity,
               lga AS region,
               source AS source,
               COALESCE(last_active_at::timestamptz, updated_at) AS observed_at,
               beneficiaries_served::double precision AS metric_value,
               agency_slug AS extra
          FROM "{schema}".aid_coverage
         WHERE COALESCE(last_active_at::timestamptz, updated_at) >= :cutoff

        UNION ALL

        SELECT 'poverty_village' AS kind,
               '' AS subtype,
               CASE
                 WHEN poverty_score >= 0.8 THEN 'high'
                 WHEN poverty_score >= 0.6 THEN 'medium'
                 ELSE 'low'
               END AS severity,
               COALESCE(settlement_name, lga, '') AS region,
               source AS source,
               created_at AS observed_at,
               poverty_score AS metric_value,
               lga AS extra
          FROM "{schema}".poverty_villages
         WHERE created_at >= :cutoff

         ORDER BY observed_at DESC
         LIMIT 50
    """
    result = await session.execute(text(sql), {"cutoff": cutoff})
    return [dict(r) for r in result.mappings().all()]


def _row_to_feed_event(tenant_id: str, row: dict) -> FeedEvent | None:
    """Map normalized DB row → FeedEvent + write a human-readable title."""
    kind: FeedKind = row["kind"]
    severity = _normalize_severity(row.get("severity"))
    region = (row.get("region") or "").strip() or None
    source = (row.get("source") or "unknown").strip()
    observed_at = row.get("observed_at")
    if not isinstance(observed_at, datetime):
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    if kind == "alert_event":
        return FeedEvent(
            kind=kind,
            tenant_id=tenant_id,
            title=_alert_event_title(row, tenant_id, region),
            region=region,
            tag="Encroachment" if row.get("subtype") == "encroachment" else "Disaster",
            severity=severity,
            source=source,
            observed_at=observed_at,
        )
    if kind == "ndvi_anomaly":
        z = row.get("metric_value") or 0.0
        flagged = row.get("subtype") == "anomaly"
        return FeedEvent(
            kind=kind,
            tenant_id=tenant_id,
            title=(
                f"NDVI anomaly z={z:.2f} — {region or tenant_id}" if flagged
                else f"NDVI baseline holding — {region or tenant_id}"
            ),
            region=region,
            tag="Agriculture",
            severity=severity if flagged else "low",
            source=source,
            observed_at=observed_at,
        )
    if kind == "shock_event":
        et = (row.get("subtype") or "").lower()
        emoji = "Flood" if et == "flood" else "Drought" if et == "drought" else "Shock"
        return FeedEvent(
            kind=kind,
            tenant_id=tenant_id,
            title=f"{emoji} — {region or tenant_id}",
            region=region,
            tag="Disaster",
            severity=severity,
            source=source,
            observed_at=observed_at,
        )
    if kind == "aid_coverage":
        bens = int(row.get("metric_value") or 0)
        agency = (row.get("extra") or "").upper()
        return FeedEvent(
            kind=kind,
            tenant_id=tenant_id,
            title=(
                f"{agency} coverage updated — {region or tenant_id} "
                f"(~{bens:,} beneficiaries)"
            ),
            region=region,
            tag="Aid",
            severity="low",
            source=source,
            observed_at=observed_at,
        )
    if kind == "poverty_village":
        score = row.get("metric_value") or 0.0
        return FeedEvent(
            kind=kind,
            tenant_id=tenant_id,
            title=(
                f"Poverty hotspot — {region or tenant_id} "
                f"({int(score * 100)}% index)"
            ),
            region=row.get("extra") or region,
            tag="Poverty",
            severity=severity,
            source=source,
            observed_at=observed_at,
        )
    return None


def _alert_event_title(row: dict, tenant_id: str, region: str | None) -> str:
    subtype = (row.get("subtype") or "").lower()
    area = row.get("metric_value")
    where = region or tenant_id
    if subtype == "encroachment":
        return f"Encroachment detected — {where}"
    if subtype == "fire" or subtype == "heat":
        if area:
            return f"Heat signature — {where} (~{int(area)} ha)"
        return f"Heat signature — {where}"
    if subtype == "conflict":
        return f"Conflict-risk alert — {where}"
    return f"Alert — {where}"


def _normalize_severity(value: object) -> FeedSeverity:
    """Map free-text severities + confidence bands to the canonical enum."""
    if not isinstance(value, str):
        return "low"
    v = value.strip().lower()
    if v in ("critical", "crit"):
        return "critical"
    if v in ("high", "high_confidence"):
        return "high"
    if v in ("medium", "med", "moderate"):
        return "medium"
    if v in ("low", "low_confidence"):
        return "low"
    # ConfidenceBand values from CropGuard:
    if v == "high":
        return "high"
    if v == "medium":
        return "medium"
    return "low"
