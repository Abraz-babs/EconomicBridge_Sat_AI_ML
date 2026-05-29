"""Tests for the AWS SNS SMS gateway.

boto3 is never called: a fake SNS client is injected, so these run without
AWS creds or network. What we pin:
  * not-configured → failed SendResult (no publish attempted)
  * success → 'sent' with the SNS MessageId
  * transactional SMSType + SenderID attributes are passed to publish
  * a boto error → failed SendResult (never raises out of send())
  * a response with no MessageId → failed
"""
from __future__ import annotations

from typing import Any

import pytest

from gateways.sns import SnsGateway


class _FakeSns:
    """Records publish() kwargs; returns a canned response or raises."""

    def __init__(self, *, response: dict[str, Any] | None = None, error: Exception | None = None):
        self._response = response if response is not None else {"MessageId": "sns-msg-123"}
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


@pytest.fixture(autouse=True)
def _enable_sns(monkeypatch):
    monkeypatch.setenv("SNS_ENABLED", "true")
    monkeypatch.setenv("SNS_SENDER_ID", "EconBridge")
    from config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_send_not_configured_returns_failed(monkeypatch):
    monkeypatch.setenv("SNS_ENABLED", "false")
    from config import get_settings
    get_settings.cache_clear()
    fake = _FakeSns()
    gw = SnsGateway(client=fake)
    result = await gw.send(phone_e164="+2348012345678", message="hi")
    assert result.status == "failed"
    assert "not enabled" in (result.error_message or "")
    assert fake.calls == []  # never attempted a publish


@pytest.mark.asyncio
async def test_send_success_returns_sent_with_message_id():
    fake = _FakeSns(response={"MessageId": "abc-789"})
    gw = SnsGateway(client=fake)
    result = await gw.send(phone_e164="+2348012345678", message="Flood alert")
    assert result.provider == "sns"
    assert result.status == "sent"
    assert result.provider_message_id == "abc-789"


@pytest.mark.asyncio
async def test_send_passes_transactional_and_sender_attributes():
    fake = _FakeSns()
    gw = SnsGateway(client=fake)
    await gw.send(phone_e164="+2348012345678", message="x", sender_id="Bizra")
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["PhoneNumber"] == "+2348012345678"
    attrs = call["MessageAttributes"]
    assert attrs["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional"
    assert attrs["AWS.SNS.SMS.SenderID"]["StringValue"] == "Bizra"


@pytest.mark.asyncio
async def test_send_boto_error_returns_failed_not_raises():
    fake = _FakeSns(error=RuntimeError("throttled"))
    gw = SnsGateway(client=fake)
    result = await gw.send(phone_e164="+2348012345678", message="x")
    assert result.status == "failed"
    assert "throttled" in (result.error_message or "")


@pytest.mark.asyncio
async def test_send_missing_message_id_is_failed():
    fake = _FakeSns(response={})
    gw = SnsGateway(client=fake)
    result = await gw.send(phone_e164="+2348012345678", message="x")
    assert result.status == "failed"
