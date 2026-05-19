"""Mock SMS gateway — used in dev when no real provider key is configured.

Logs the would-be SMS to stdout and returns a deterministic `sent_mock`
result. The dispatcher uses this automatically when Termii/Twilio aren't
configured, so the whole pipeline (subscriber lookup → render → outbox
INSERT → status update) is exercisable end-to-end without external
dependencies.
"""
from __future__ import annotations

import logging
import secrets

from .base import GatewayName, SendResult

log = logging.getLogger(__name__)


class MockGateway:
    name: GatewayName = "mock"

    async def send(
        self, *, phone_e164: str, message: str, sender_id: str | None = None
    ) -> SendResult:
        msg_id = f"mock_{secrets.token_hex(8)}"
        log.info(
            "MOCK SMS  to=%s  from=%s  id=%s  body=%r",
            phone_e164, sender_id or "EconoBridge", msg_id, message,
        )
        return SendResult(
            provider="mock",
            status="mock",
            provider_message_id=msg_id,
        )
