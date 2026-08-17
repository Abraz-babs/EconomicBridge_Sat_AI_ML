"""Conflict-alert dispatcher — the orchestration layer.

End-to-end flow:
  1. Look up active subscribers in tenant_<id>.alert_subscribers
  2. Filter by severity_threshold + alert_types preferences
  3. For each match, INSERT into public.sms_outbox (status='queued')
  4. Idempotency check: skip subscribers already dispatched for the same
     prediction_id (uniqueness enforced at DB level via the partial index)
  5. Render the SMS body
  6. Call the per-tenant gateway (Termii / Twilio / Mock)
  7. UPDATE the outbox row with the gateway result (status + provider id)

Each step is a small, testable function. The DB writes are commit-after-
gateway-call so a network failure on the gateway side still leaves an
auditable 'queued' row that a future Celery worker can retry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import set_tenant_schema
from gateways.base import SendResult, SmsGateway
from services.messages import (
    RenderContext,
    region_label,
    render_conflict_sms,
    render_farmer_sms,
    should_dispatch,
)
from services.providers import resolve_gateway

log = logging.getLogger(__name__)

# PostgreSQL SQLSTATEs. 23505 (unique_violation) is the one we expect and
# handle: the partial unique indexes from migration 0026 firing on a genuine
# re-dispatch. Anything else arriving as IntegrityError is a bug in our INSERT,
# not a duplicate, and must not be reported as one — see _is_duplicate_violation.
PG_UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True, slots=True)
class SubscriberRow:
    id: UUID
    phone_e164: str
    language: str
    lga: str | None
    severity_threshold: str
    alert_types: list[str] | None


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    subscriber_id: UUID
    phone_e164: str
    provider: str
    status: str
    provider_message_id: str | None
    error_message: str | None
    skipped_duplicate: bool = False
    # The language this recipient's message was rendered in. Defaulted so the
    # conflict path is unaffected; the advisory path sets it, because "which
    # languages did this actually go out in" is the question an operator asks
    # when part of the copy is still awaiting native-speaker confirmation.
    language: str = "en"


async def fetch_matching_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    severity: str,
    alert_type: str,
    lga: str | None,
) -> list[SubscriberRow]:
    """Return active subscribers whose preferences match an incoming alert.

    LGA filter: if the alert has an LGA, only subscribers in that LGA OR
    subscribers with NULL LGA (tenant-wide opt-in) receive it.
    """
    await set_tenant_schema(session, tenant_id)

    base_sql = (
        "SELECT id, phone_e164, language, lga, severity_threshold, alert_types "
        "FROM alert_subscribers "
        "WHERE is_active = TRUE"
    )
    params: dict[str, object] = {}
    if lga:
        base_sql += " AND (lga = :lga OR lga IS NULL)"
        params["lga"] = lga

    rows = (await session.execute(text(base_sql), params)).mappings().all()
    matched: list[SubscriberRow] = []
    for r in rows:
        if not should_dispatch(
            severity=severity,
            threshold=r["severity_threshold"],
            alert_types=r["alert_types"],
            incoming_alert_type=alert_type,
        ):
            continue
        matched.append(
            SubscriberRow(
                id=r["id"],
                phone_e164=r["phone_e164"],
                language=r["language"],
                lga=r["lga"],
                severity_threshold=r["severity_threshold"],
                alert_types=list(r["alert_types"]) if r["alert_types"] else None,
            )
        )
    return matched


async def _insert_outbox_row(
    session: AsyncSession,
    *,
    outbox_id: UUID,
    tenant_id: str,
    subscriber: SubscriberRow,
    message: str,
    severity: str,
    alert_type: str,
    related_prediction_id: UUID | None,
    related_alert_id: UUID | None,
    provider: str,
    trace_id: UUID,
) -> bool:
    """INSERT a queued outbox row. Returns False on idempotency collision."""
    # Outbox is in public — clear the per-tenant search_path before write.
    await session.execute(text("SET search_path TO public"))
    try:
        await session.execute(
            text(
                """
                INSERT INTO sms_outbox (
                    id, tenant_id, subscriber_id, phone_e164, message, language,
                    related_prediction_id, related_alert_id, severity, alert_type,
                    provider, status, trace_id, queued_at
                ) VALUES (
                    :id, :tenant_id, :subscriber_id, :phone_e164, :message, :language,
                    :prediction_id, :alert_id, :severity, :alert_type,
                    :provider, 'queued', :trace_id, NOW()
                )
                """
            ),
            {
                "id": outbox_id,
                "tenant_id": tenant_id,
                "subscriber_id": subscriber.id,
                "phone_e164": subscriber.phone_e164,
                "message": message,
                "language": subscriber.language,
                "prediction_id": related_prediction_id,
                "alert_id": related_alert_id,
                "severity": severity,
                "alert_type": alert_type,
                "provider": provider,
                "trace_id": trace_id,
            },
        )
        return True
    except IntegrityError as exc:
        await session.rollback()
        if _is_duplicate_violation(exc):
            # The idempotency rule from 0026 — (prediction_id, subscriber_id)
            # or (alert_id, subscriber_id) UNIQUE — caught a real re-dispatch.
            return False
        # Anything else is a defect in what we are inserting, and silence here
        # is expensive: this branch used to swallow a CHECK violation and
        # report it as `skipped_duplicate`, which would have shown a clean
        # "no duplicates to send" result while delivering nothing at all
        # (see migration 0043 — 'sns' was missing from the provider CHECK).
        log.error(
            "dispatcher: outbox INSERT rejected for tenant=%s subscriber=%s "
            "provider=%s — NOT a duplicate (sqlstate=%s): %s",
            tenant_id, subscriber.id, provider, _sqlstate(exc), exc,
        )
        raise


def _sqlstate(exc: IntegrityError) -> str | None:
    """Best-effort SQLSTATE from a wrapped driver error.

    asyncpg exposes `.sqlstate`; psycopg exposes `.pgcode`. Returning None when
    neither is present makes `_is_duplicate_violation` fail closed (treat as
    NOT a duplicate), which surfaces the error rather than hiding it.
    """
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _is_duplicate_violation(exc: IntegrityError) -> bool:
    """True only for a unique-constraint violation (the idempotency case)."""
    return _sqlstate(exc) == PG_UNIQUE_VIOLATION


async def _finalise_outbox_row(
    session: AsyncSession,
    *,
    outbox_id: UUID,
    result: SendResult,
) -> None:
    await session.execute(text("SET search_path TO public"))
    await session.execute(
        text(
            """
            UPDATE sms_outbox
            SET status = :status,
                provider_message_id = :provider_message_id,
                error_message = :error_message,
                cost_units = :cost_units,
                cost_currency = :cost_currency,
                dispatched_at = NOW()
            WHERE id = :id
            """
        ),
        {
            "id": outbox_id,
            "status": result.status,
            "provider_message_id": result.provider_message_id,
            "error_message": result.error_message,
            "cost_units": result.cost_units,
            "cost_currency": result.cost_currency,
        },
    )


async def fetch_advisory_subscribers(
    session: AsyncSession, *, tenant_id: str, advisory: str, lga: str | None,
) -> list[SubscriberRow]:
    """Active subscribers for a farmer advisory in `lga`.

    Deliberately does NOT apply `should_dispatch`. That gate ranks an alert's
    severity against the subscriber's threshold, which suits a graded conflict
    alert; a farmer advisory is not graded — "heavy rain was recorded" is either
    relevant to your LGA or it is not. Applying the default 'high' threshold
    would silently drop every advisory.

    `alert_types` is still honoured: a subscriber who explicitly narrowed their
    subscription chose that, and an advisory is a type like any other.
    """
    await set_tenant_schema(session, tenant_id)

    sql = (
        "SELECT id, phone_e164, language, lga, severity_threshold, alert_types "
        "FROM alert_subscribers "
        "WHERE is_active = TRUE"
    )
    params: dict[str, object] = {}
    if lga:
        sql += " AND (lga = :lga OR lga IS NULL)"
        params["lga"] = lga

    rows = (await session.execute(text(sql), params)).mappings().all()
    return [
        SubscriberRow(
            id=r["id"], phone_e164=r["phone_e164"], language=r["language"],
            lga=r["lga"], severity_threshold=r["severity_threshold"],
            alert_types=list(r["alert_types"]) if r["alert_types"] else None,
        )
        for r in rows
        if not r["alert_types"] or advisory in r["alert_types"]
    ]


async def dispatch_farmer_advisory(
    session: AsyncSession,
    *,
    tenant_id: str,
    advisory: str,
    lga: str,
    state: str,
    related_alert_id: UUID | None,
    trace_id: UUID,
    gateway: SmsGateway | None = None,
    dry_run: bool = False,
) -> list[DispatchOutcome]:
    """Send one farmer advisory to every matching subscriber, in their language.

    Distinct from `dispatch_conflict_alert` because the message is different in
    kind, not just wording: `render_conflict_sms` produces an agency-desk line
    ("[CRITICAL] EconomicBridge — Flood alert in X. ETA 48h. 120 ha at risk."),
    while a farmer holding a feature phone needs one observation and one action.
    See the FARMER_ADVISORIES block in services/messages.py.

    `render_farmer_sms` raises for a withheld advisory type (drought, flood,
    conflict) — that raise is the safety gate and is deliberately not caught
    here; the router turns it into a 400.

    `dry_run` renders and matches without sending or writing an outbox row, so
    the exact set of recipients and message bodies can be inspected before any
    money is spent. Worth using for the first send of a pilot.
    """
    subscribers = await fetch_advisory_subscribers(
        session, tenant_id=tenant_id, advisory=advisory, lga=lga,
    )
    if not subscribers:
        log.info(
            "advisory: no subscribers matched  tenant=%s advisory=%s lga=%s",
            tenant_id, advisory, lga,
        )
        return []

    gw = gateway or resolve_gateway(tenant_id)
    outcomes: list[DispatchOutcome] = []

    for sub in subscribers:
        message = render_farmer_sms(
            advisory, lga=lga, state=state, lang=sub.language,
            # Territory name for the enrolment line, in the subscriber's own
            # language — 'Kebbi State' / 'Jihar Kebbi', never 'Ghana State'.
            region=region_label(tenant_id, sub.language),
        )
        if dry_run:
            outcomes.append(
                DispatchOutcome(
                    subscriber_id=sub.id, phone_e164=sub.phone_e164,
                    provider=gw.name, status="dry_run",
                    provider_message_id=None,
                    # The rendered body rides back in error_message so a dry run
                    # shows exactly what each recipient would receive. Named for
                    # the shared DispatchSummary shape, not for an error.
                    error_message=message,
                    language=sub.language,
                )
            )
            continue

        outbox_id = uuid4()
        inserted = await _insert_outbox_row(
            session,
            outbox_id=outbox_id,
            tenant_id=tenant_id,
            subscriber=sub,
            message=message,
            # Farmer advisories are not severity-graded; the column is nullable
            # and a made-up severity would pollute reporting.
            severity=None,
            alert_type=advisory,
            related_prediction_id=None,
            related_alert_id=related_alert_id,
            provider=gw.name,
            trace_id=trace_id,
        )
        if not inserted:
            outcomes.append(
                DispatchOutcome(
                    subscriber_id=sub.id, phone_e164=sub.phone_e164,
                    provider=gw.name, status="skipped_duplicate",
                    provider_message_id=None, error_message=None,
                    skipped_duplicate=True, language=sub.language,
                )
            )
            continue
        await session.commit()

        result = await gw.send(phone_e164=sub.phone_e164, message=message)
        await _finalise_outbox_row(session, outbox_id=outbox_id, result=result)
        await session.commit()

        outcomes.append(
            DispatchOutcome(
                subscriber_id=sub.id, phone_e164=sub.phone_e164,
                provider=gw.name, status=result.status,
                provider_message_id=result.provider_message_id,
                error_message=result.error_message,
                language=sub.language,
            )
        )
        log.info(
            "advisory: tenant=%s advisory=%s subscriber=%s provider=%s status=%s",
            tenant_id, advisory, sub.id, gw.name, result.status,
        )

    return outcomes


async def dispatch_conflict_alert(
    session: AsyncSession,
    *,
    tenant_id: str,
    severity: str,
    alert_type: str,
    lga: str | None,
    zone_name: str | None,
    affected_area_ha: float | None,
    livelihoods_at_risk: int | None,
    eta_hours: int | None,
    related_prediction_id: UUID | None,
    related_alert_id: UUID | None,
    trace_id: UUID,
    gateway: SmsGateway | None = None,
) -> list[DispatchOutcome]:
    """Run the end-to-end dispatch loop. Returns one outcome per subscriber.

    Caller owns the AsyncSession (FastAPI dependency or background worker).
    Each row commits after its INSERT so a network failure on one send
    doesn't lose the audit trail for the others.
    """
    subscribers = await fetch_matching_subscribers(
        session, tenant_id=tenant_id, severity=severity,
        alert_type=alert_type, lga=lga,
    )

    if not subscribers:
        log.info(
            "dispatcher: no subscribers matched  tenant=%s severity=%s alert_type=%s lga=%s",
            tenant_id, severity, alert_type, lga,
        )
        return []

    # Build the render context once; the body is rendered per subscriber in
    # their own language (the dispatcher reads subscriber.language).
    ctx = RenderContext(
        tenant_id=tenant_id,
        severity=severity,
        alert_type=alert_type,
        lga=lga,
        zone_name=zone_name,
        affected_area_ha=affected_area_ha,
        livelihoods_at_risk=livelihoods_at_risk,
        eta_hours=eta_hours,
    )
    gw = gateway or resolve_gateway(tenant_id)

    outcomes: list[DispatchOutcome] = []
    for sub in subscribers:
        message = render_conflict_sms(ctx, sub.language)
        outbox_id = uuid4()
        inserted = await _insert_outbox_row(
            session,
            outbox_id=outbox_id,
            tenant_id=tenant_id,
            subscriber=sub,
            message=message,
            severity=severity,
            alert_type=alert_type,
            related_prediction_id=related_prediction_id,
            related_alert_id=related_alert_id,
            provider=gw.name,
            trace_id=trace_id,
        )
        if not inserted:
            outcomes.append(
                DispatchOutcome(
                    subscriber_id=sub.id, phone_e164=sub.phone_e164,
                    provider=gw.name, status="skipped_duplicate",
                    provider_message_id=None, error_message=None,
                    skipped_duplicate=True,
                )
            )
            continue
        await session.commit()  # ensure the queued row is durable

        result = await gw.send(phone_e164=sub.phone_e164, message=message)
        await _finalise_outbox_row(session, outbox_id=outbox_id, result=result)
        await session.commit()

        outcomes.append(
            DispatchOutcome(
                subscriber_id=sub.id, phone_e164=sub.phone_e164,
                provider=gw.name, status=result.status,
                provider_message_id=result.provider_message_id,
                error_message=result.error_message,
            )
        )
        log.info(
            "dispatcher: tenant=%s subscriber=%s provider=%s status=%s",
            tenant_id, sub.id, gw.name, result.status,
        )

    return outcomes
