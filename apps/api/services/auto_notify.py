"""Best-effort bridge from a persisted alert to the notifications service.

When a ShockGuard/Farmland alert is persisted, the API can fire an SMS
dispatch by POSTing to the notifications service's /notify/conflict. This is
deliberately fire-and-forget: a notify failure (service down, DPA missing,
network) is logged but NEVER breaks the originating request.

Gated by `auto_notify_enabled` (default False) — auto-sending PII SMS must be
opted into. Requires `notify_system_org_id` to be a real org holding a signed
DPA for the tenant (in dev, the demo org seeded by scripts/seed_demo_dpa.py).

Production hardening still needed: a dedicated system organisation + DPAs,
per-event dedup/rate-limiting, and a detection→notify path that is
scheduler-driven rather than tied to an on-demand scan.
"""
from __future__ import annotations

import logging
from uuid import UUID

import httpx

from config import get_settings

log = logging.getLogger(__name__)


async def fire_conflict_notification(
    *,
    tenant_id: str,
    severity: str,
    alert_type: str,
    lga: str | None,
    zone_name: str | None,
    affected_area_ha: float | None,
    livelihoods_at_risk: int | None,
    eta_hours: int | None,
    alert_id: UUID | None,
) -> None:
    """POST one dispatch to the notifications service. Never raises."""
    s = get_settings()
    if not s.auto_notify_enabled or not s.notify_system_org_id:
        return

    payload = {
        "tenant_id": tenant_id,
        "severity": severity,
        "alert_type": alert_type,
        "lga": lga,
        "zone_name": zone_name,
        "affected_area_ha": affected_area_ha,
        "livelihoods_at_risk": livelihoods_at_risk,
        "eta_hours": eta_hours,
        "alert_id": str(alert_id) if alert_id else None,
    }
    headers = {
        "X-Tenant-Id": tenant_id,
        "X-Organisation-Id": s.notify_system_org_id,
    }
    url = f"{s.notify_base_url}/notify/conflict"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.warning(
                "auto-notify: notifications service returned %s for tenant=%s alert=%s",
                resp.status_code, tenant_id, alert_id,
            )
        else:
            log.info(
                "auto-notify: dispatched tenant=%s alert_type=%s alert=%s",
                tenant_id, alert_type, alert_id,
            )
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the caller
        log.warning("auto-notify: best-effort dispatch failed (%s)", exc)
