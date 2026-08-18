"""Send rainfall advisories to subscribed farmers, automatically.

This is the only place in the platform where satellite output reaches a member
of the public with no human in between. Everything here is written on that
assumption: the expensive failure is not a missed message, it is a wrong or
repeated one landing on a smallholder's phone at 6am.

WHY IT EXISTS
-------------
The rainfall scan runs daily at 08:00 UTC and writes advisories to
`rainfall_advisory_history`. Until now a farmer only heard about one if an
operator noticed and dispatched by hand, which means the useful window — the
morning it rained — was usually missed. Kebbi fires roughly once or twice a
month in season, so automating it fits comfortably inside the "2-4 msgs a
month" the enrolment SMS promises.

THE GUARDS, AND WHY EACH ONE
----------------------------
* OFF by default (`farmer_sms_enabled`), enabled per environment.
* Explicit tenant allowlist. A tenant acquiring subscribers must never begin
  auto-sending as a side effect of someone loading a roster.
* No DPA organisation configured -> nothing sends. The notify endpoint is
  PII-gated and this refuses before even calling it.
* Idempotency is a DB commit, not a variable: an advisory is dispatched only
  when `sms_dispatched_at IS NULL`, and that column is stamped immediately
  after the gateway accepts. `rainfall_advisory_history` is UNIQUE on
  (lga, observed_date), so one rainfall day in one LGA can produce at most one
  batch — forever, across redeploys and re-runs.
* Daily and monthly caps counted from the same column. The monthly cap is what
  keeps the enrolment promise honest.
* Only 'rainfall'. The withheld types (drought, flood, conflict) are refused
  again at the notifications layer, but this never asks for them in the first
  place — two independent locks on the door that matters most.
* Nothing here raises into the scan. A failed dispatch must never lose the
  advisory itself; the row stays undispatched and is retried next run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db import set_tenant_schema

log = logging.getLogger(__name__)

# The only advisory this task will ever ask for. Not a parameter: a caller
# should not be able to widen the blast radius by passing a different string.
ADVISORY = "rainfall"

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    tenant: str
    considered: int
    sent: int
    recipients: int
    skipped_capped: int
    failed: int

    def summary(self) -> str:
        return (
            f"{self.tenant}: {self.sent} advisory batch(es) to "
            f"{self.recipients} recipient(s); considered={self.considered} "
            f"capped={self.skipped_capped} failed={self.failed}"
        )


def enabled_tenants() -> list[str]:
    s = get_settings()
    if not s.farmer_sms_enabled:
        return []
    if not s.notifications_org_id:
        # Loud, because this looks identical to "quiet weather" from outside.
        log.warning(
            "farmer sms: enabled but notifications_org_id is unset — refusing "
            "to dispatch (the notify endpoint is DPA-gated)"
        )
        return []
    return [t.strip() for t in s.farmer_sms_tenants.split(",") if t.strip()]


async def _counts(session: AsyncSession) -> tuple[int, int]:
    """(dispatched today, dispatched this calendar month) for this tenant."""
    row = (await session.execute(text(
        """
        SELECT
          COUNT(*) FILTER (WHERE sms_dispatched_at >= date_trunc('day', NOW())),
          COUNT(*) FILTER (WHERE sms_dispatched_at >= date_trunc('month', NOW()))
        FROM rainfall_advisory_history
        WHERE sms_dispatched_at IS NOT NULL
        """
    ))).first()
    return (row[0] or 0, row[1] or 0) if row else (0, 0)


async def _pending(session: AsyncSession) -> list[dict]:
    """Advisories not yet sent, newest first.

    Bounded to the last 2 days on purpose. If dispatch has been broken for a
    week we do NOT want it recovering by sending seven days of stale rainfall
    the moment it is fixed — "heavy rain recorded" about last Tuesday is worse
    than silence. Old rows simply stay undispatched, which the history table
    honestly records.
    """
    rows = (await session.execute(text(
        """
        SELECT id, lga, severity, observed_date, rain_mm_day
        FROM rainfall_advisory_history
        WHERE sms_dispatched_at IS NULL
          AND observed_date >= (CURRENT_DATE - INTERVAL '2 days')
        ORDER BY advised_at DESC
        """
    ))).mappings().all()
    return [dict(r) for r in rows]


async def _notify(client: httpx.AsyncClient, tenant: str, lga: str) -> dict | None:
    """POST the advisory to the notifications service. None on any failure."""
    s = get_settings()
    try:
        resp = await client.post(
            f"{s.notifications_base_url}/notify/advisory",
            json={
                "tenant_id": tenant,
                "advisory": ADVISORY,
                "lga": lga,
                "dry_run": False,
            },
            headers={
                "X-Tenant-Id": tenant,
                "X-Organisation-Id": s.notifications_org_id,
            },
        )
    except httpx.HTTPError as exc:
        log.warning("farmer sms: %s/%s network error: %r", tenant, lga, exc)
        return None
    if resp.status_code != 200:
        log.warning(
            "farmer sms: %s/%s refused by notifications (%s): %s",
            tenant, lga, resp.status_code, resp.text[:200],
        )
        return None
    return (resp.json() or {}).get("data") or {}


async def dispatch_for_tenant(
    session: AsyncSession, tenant: str, *, client: httpx.AsyncClient | None = None,
) -> DispatchResult:
    """Send every undispatched recent advisory for one tenant, within caps."""
    s = get_settings()
    await set_tenant_schema(session, tenant)

    pending = await _pending(session)
    if not pending:
        return DispatchResult(tenant, 0, 0, 0, 0, 0)

    today, month = await _counts(session)
    sent = recipients = capped = failed = 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        for row in pending:
            if today >= s.farmer_sms_max_per_day:
                capped += 1
                continue
            if month >= s.farmer_sms_max_per_month:
                capped += 1
                continue

            data = await _notify(client, tenant, row["lga"])
            if data is None:
                failed += 1
                continue

            n = int(data.get("dispatched") or 0)
            if n == 0:
                # No subscribers matched. Mark it anyway: re-asking tomorrow
                # would only re-discover that nobody is listening, and leaving
                # it pending makes the backlog look like a fault.
                log.info(
                    "farmer sms: %s/%s had no subscribers — marking handled",
                    tenant, row["lga"],
                )

            await session.execute(text(
                "UPDATE rainfall_advisory_history "
                "SET sms_dispatched_at = NOW(), sms_recipients = :n "
                "WHERE id = :id"
            ), {"n": n, "id": row["id"]})
            await session.commit()

            sent += 1
            today += 1
            month += 1
            recipients += n
            log.info(
                "farmer sms: %s/%s (%s, %.1fmm on %s) -> %d recipient(s)",
                tenant, row["lga"], row["severity"], row["rain_mm_day"] or 0.0,
                row["observed_date"], n,
            )
    finally:
        if owns_client:
            await client.aclose()

    if capped:
        log.warning(
            "farmer sms: %s held back %d advisory(ies) at the cap "
            "(day %d/%d, month %d/%d) — the enrolment SMS promises 2-4 a month",
            tenant, capped, today, s.farmer_sms_max_per_day,
            month, s.farmer_sms_max_per_month,
        )
    return DispatchResult(tenant, len(pending), sent, recipients, capped, failed)


async def run_farmer_sms_dispatch() -> dict[str, str]:
    """Dispatch for every enabled tenant. Never raises — the scan owns the data."""
    tenants = enabled_tenants()
    if not tenants:
        return {}

    from db import get_session_factory

    out: dict[str, str] = {}
    factory = get_session_factory()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for tenant in tenants:
            try:
                async with factory() as session:
                    res = await dispatch_for_tenant(session, tenant, client=client)
                    out[tenant] = res.summary()
                    log.info("farmer sms: %s", res.summary())
            except Exception as exc:  # noqa: BLE001 — one tenant must not stop the rest
                out[tenant] = f"failed: {exc!r}"
                log.exception("farmer sms: %s dispatch failed", tenant)
    return out
