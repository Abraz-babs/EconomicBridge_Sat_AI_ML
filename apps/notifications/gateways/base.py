"""Shared types for SMS gateway clients.

`SmsGateway` is the abstract contract. Each provider implementation
(`TermiiGateway`, `TwilioGateway`, `MockGateway`) returns the same shape so
the dispatcher and the outbox writer don't have to special-case providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

GatewayName = Literal["termii", "twilio", "mock"]


@dataclass(frozen=True, slots=True)
class SendResult:
    """Outcome of a single SMS send. Maps 1:1 to a public.sms_outbox row."""

    provider: GatewayName
    status: Literal["sent", "delivered", "failed", "mock"]
    provider_message_id: str | None = None
    error_message: str | None = None
    cost_units: float | None = None
    cost_currency: str | None = None


class SmsGateway(Protocol):
    """Provider clients implement this single async method."""

    name: GatewayName

    async def send(
        self, *, phone_e164: str, message: str, sender_id: str | None = None
    ) -> SendResult:
        ...
