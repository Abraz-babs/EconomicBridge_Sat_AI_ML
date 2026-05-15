"""Unit tests for Termii + Twilio response parsers (no network)."""
from __future__ import annotations

import httpx

from gateways.termii import _parse_response as parse_termii
from gateways.twilio import _parse_response as parse_twilio


def _resp(status: int, body: object, *, json: bool = True) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=body if json else None,
        content=body if not json else None,
    )


# ─── Termii ───────────────────────────────────────────────────────────────


def test_termii_success_response_marks_sent() -> None:
    r = _resp(
        200,
        {
            "message_id": "abc-123",
            "message": "Successfully Sent",
            "balance": 950.5,
            "code": "ok",
        },
    )
    result = parse_termii(r)
    assert result.status == "sent"
    assert result.provider == "termii"
    assert result.provider_message_id == "abc-123"
    assert result.cost_units == 950.5
    assert result.cost_currency == "NGN"


def test_termii_insufficient_funds_marks_failed() -> None:
    r = _resp(402, {"code": "InsufficientFunds", "message": "Top up account"})
    result = parse_termii(r)
    assert result.status == "failed"
    assert "InsufficientFunds" in (result.error_message or "")


def test_termii_non_json_response_marks_failed() -> None:
    r = httpx.Response(status_code=502, text="Bad Gateway")
    result = parse_termii(r)
    assert result.status == "failed"


# ─── Twilio ───────────────────────────────────────────────────────────────


def test_twilio_success_response_marks_sent() -> None:
    r = _resp(
        201,
        {
            "sid": "SM123",
            "status": "queued",
            "price": "-0.0075",
            "price_unit": "USD",
        },
    )
    result = parse_twilio(r)
    assert result.status == "sent"
    assert result.provider_message_id == "SM123"
    assert abs(result.cost_units - 0.0075) < 1e-9
    assert result.cost_currency == "USD"


def test_twilio_delivered_status_passes_through() -> None:
    r = _resp(200, {"sid": "SM456", "status": "delivered", "price": None, "price_unit": "USD"})
    result = parse_twilio(r)
    assert result.status == "delivered"


def test_twilio_failed_status_marks_failed() -> None:
    r = _resp(200, {"sid": "SM789", "status": "failed"})
    result = parse_twilio(r)
    assert result.status == "failed"


def test_twilio_4xx_marks_failed_with_error() -> None:
    r = _resp(400, {"code": 21211, "message": "Invalid 'To' Phone Number"})
    result = parse_twilio(r)
    assert result.status == "failed"
    assert "Invalid" in (result.error_message or "")
