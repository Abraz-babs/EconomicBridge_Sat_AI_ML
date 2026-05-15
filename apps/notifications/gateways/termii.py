"""Termii SMS gateway client (Nigerian carriers).

API: https://developers.termii.com/messaging-api
Endpoint used: POST /api/sms/send
Auth: `api_key` in JSON body (NOT bearer header — Termii quirk).

This client is async-only (httpx.AsyncClient). The dispatcher's caller
already runs inside an event loop, so we never block.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import get_settings

from .base import GatewayName, SendResult

log = logging.getLogger(__name__)


class TermiiGateway:
    name: GatewayName = "termii"

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http  # injectable for tests

    @property
    def configured(self) -> bool:
        return bool(self._settings.termii_api_key)

    async def send(
        self, *, phone_e164: str, message: str, sender_id: str | None = None
    ) -> SendResult:
        if not self.configured:
            return SendResult(
                provider="termii",
                status="failed",
                error_message="Termii not configured (TERMII_API_KEY missing)",
            )

        payload = {
            "to": phone_e164.lstrip("+"),
            "from": sender_id or self._settings.termii_sender_id,
            "sms": message,
            "type": "plain",
            "channel": "generic",
            "api_key": self._settings.termii_api_key,
        }
        url = f"{self._settings.termii_base_url}/sms/send"

        try:
            async with self._http_ctx() as client:
                resp = await client.post(url, json=payload, timeout=15.0)
        except httpx.HTTPError as exc:
            return SendResult(
                provider="termii",
                status="failed",
                error_message=f"network: {exc.__class__.__name__}: {exc}",
            )

        return _parse_response(resp)

    def _http_ctx(self) -> "httpx.AsyncClient | _Borrowed":
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


def _parse_response(resp: httpx.Response) -> SendResult:
    """Translate Termii's response envelope to a SendResult.

    Successful responses look like:
        {"message_id": "...", "message": "Successfully Sent", "balance": 1234,
         "user": "...", "code": "ok"}
    Failed responses look like:
        {"code": "InsufficientFunds", "message": "..."}
    """
    try:
        body: dict[str, Any] = resp.json()
    except ValueError:
        return SendResult(
            provider="termii",
            status="failed",
            error_message=f"non-json response (HTTP {resp.status_code})",
        )

    if resp.status_code >= 400 or body.get("code") not in {"ok", "OK", None}:
        return SendResult(
            provider="termii",
            status="failed",
            provider_message_id=body.get("message_id"),
            error_message=f"{body.get('code', resp.status_code)}: {body.get('message')}",
        )

    return SendResult(
        provider="termii",
        status="sent",
        provider_message_id=body.get("message_id"),
        cost_units=float(body["balance"]) if "balance" in body else None,
        cost_currency="NGN" if "balance" in body else None,
    )


class _Borrowed:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client
    async def __aexit__(self, *_exc: object) -> None:
        return None
