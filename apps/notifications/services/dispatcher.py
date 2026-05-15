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
from services.messages import RenderContext, render_conflict_sms, should_dispatch
from services.providers import resolve_gateway

log = logging.getLogger(__name__)


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
    except IntegrityError:
        # Either pkey clash (vanishingly unlikely) or — more interesting — the
        # idempotency rule (prediction_id, subscriber_id) UNIQUE WHERE
        # prediction_id IS NOT NULL caught a duplicate.
        await session.rollback()
        return False


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

    message = render_conflict_sms(
        RenderContext(
            tenant_id=tenant_id,
            severity=severity,
            alert_type=alert_type,
            lga=lga,
            zone_name=zone_name,
            affected_area_ha=affected_area_ha,
            livelihoods_at_risk=livelihoods_at_risk,
            eta_hours=eta_hours,
        )
    )
    gw = gateway or resolve_gateway(tenant_id)

    outcomes: list[DispatchOutcome] = []
    for sub in subscribers:
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
