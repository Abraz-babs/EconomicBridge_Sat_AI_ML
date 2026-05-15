"""Twilio SMS gateway client (international / ECOWAS carriers).

API: https://www.twilio.com/docs/sms/api/message-resource
Endpoint: POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json
Auth: HTTP Basic with (account_sid, auth_token).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import get_settings

from .base import GatewayName, SendResult

log = logging.getLogger(__name__)


class TwilioGateway:
    name: GatewayName = "twilio"

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        return self._settings.twilio_configured

    async def send(
        self, *, phone_e164: str, message: str, sender_id: str | None = None
    ) -> SendResult:
        if not self.configured:
            return SendResult(
                provider="twilio",
                status="failed",
                error_message="Twilio not configured (SID/token/from missing)",
            )

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{self._settings.twilio_account_sid}/Messages.json"
        )
        # NOTE: Twilio Messages endpoint expects form-encoded body, not JSON.
        data = {
            "To": phone_e164,
            "From": sender_id or self._settings.twilio_from_number,
            "Body": message,
        }
        auth = (self._settings.twilio_account_sid, self._settings.twilio_auth_token)

        try:
            async with self._http_ctx() as client:
                resp = await client.post(url, data=data, auth=auth, timeout=15.0)
        except httpx.HTTPError as exc:
            return SendResult(
                provider="twilio",
                status="failed",
                error_message=f"network: {exc.__class__.__name__}: {exc}",
            )

        return _parse_response(resp)

    def _http_ctx(self) -> "httpx.AsyncClient | _Borrowed":
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


def _parse_response(resp: httpx.Response) -> SendResult:
    try:
        body: dict[str, Any] = resp.json()
    except ValueError:
        return SendResult(
            provider="twilio",
            status="failed",
            error_message=f"non-json response (HTTP {resp.status_code})",
        )

    if resp.status_code >= 400:
        return SendResult(
            provider="twilio",
            status="failed",
            provider_message_id=body.get("sid"),
            error_message=f"{body.get('code', resp.status_code)}: {body.get('message')}",
        )

    # Twilio "status" values include queued / sent / delivered / failed / undelivered
    raw_status = body.get("status", "sent")
    status = "delivered" if raw_status == "delivered" else (
        "failed" if raw_status in {"failed", "undelivered"} else "sent"
    )

    price = body.get("price")
    try:
        cost_units = abs(float(price)) if price else None
    except (TypeError, ValueError):
        cost_units = None

    return SendResult(
        provider="twilio",
        status=status,  # type: ignore[arg-type]
        provider_message_id=body.get("sid"),
        cost_units=cost_units,
        cost_currency=body.get("price_unit"),
    )


class _Borrowed:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client
    async def __aexit__(self, *_exc: object) -> None:
        return None
