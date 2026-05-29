"""AWS SNS SMS gateway — primary Nigerian carrier path (replaces Termii).

API: SNS `Publish` with a bare `PhoneNumber` (transactional SMS).
Auth: the standard AWS credential chain — the ECS task role in production,
`~/.aws`/env vars in dev. NEVER a hardcoded key (CLAUDE.md §4.1).

boto3 is synchronous, so `send()` runs the blocking `publish` call in a
worker thread via `asyncio.to_thread` to honour the async gateway contract.
boto3 is imported lazily inside the client factory so the module (and the
test suite, which injects a fake client) load without boto3 present.

SNS doesn't return a per-message price synchronously, so `cost_units` is left
None; spend is tracked via CloudWatch / the SNS usage report, not the outbox.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from config import get_settings

from .base import GatewayName, SendResult

log = logging.getLogger(__name__)


class SnsGateway:
    name: GatewayName = "sns"

    def __init__(self, *, client: Any | None = None) -> None:
        self._settings = get_settings()
        # Injected fake (tests) or a cached boto3 client (created on first use).
        self._client = client

    @property
    def configured(self) -> bool:
        return self._settings.sns_configured

    def _sns(self) -> Any:
        """Lazily build (and cache) the boto3 SNS client."""
        if self._client is None:
            import boto3  # lazy: keep module import boto3-free for tests

            self._client = boto3.client("sns", region_name=self._settings.sns_region)
        return self._client

    async def send(
        self, *, phone_e164: str, message: str, sender_id: str | None = None
    ) -> SendResult:
        if not self.configured:
            return SendResult(
                provider="sns",
                status="failed",
                error_message="AWS SNS not enabled (set SNS_ENABLED=true)",
            )

        sender = sender_id or self._settings.sns_sender_id
        attributes = {
            # Transactional → higher delivery priority + reliability than
            # the default Promotional class.
            "AWS.SNS.SMS.SMSType": {
                "DataType": "String", "StringValue": "Transactional",
            },
            "AWS.SNS.SMS.SenderID": {
                "DataType": "String", "StringValue": sender,
            },
        }
        try:
            resp = await asyncio.to_thread(
                self._sns().publish,
                PhoneNumber=phone_e164,
                Message=message,
                MessageAttributes=attributes,
            )
        except Exception as exc:  # noqa: BLE001 — any boto/network error → failed row
            return SendResult(
                provider="sns",
                status="failed",
                error_message=f"{exc.__class__.__name__}: {exc}",
            )
        return _parse_response(resp)


def _parse_response(resp: dict[str, Any]) -> SendResult:
    """SNS Publish returns {'MessageId': ...} on success."""
    message_id = resp.get("MessageId") if isinstance(resp, dict) else None
    if not message_id:
        return SendResult(
            provider="sns",
            status="failed",
            error_message="SNS publish returned no MessageId",
        )
    return SendResult(
        provider="sns",
        status="sent",
        provider_message_id=message_id,
    )
