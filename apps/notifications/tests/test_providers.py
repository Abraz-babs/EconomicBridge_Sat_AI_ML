"""Unit tests for the tenant→gateway selector + mock fallback."""
from __future__ import annotations

import pytest

from config import get_settings
from gateways.mock import MockGateway
from gateways.termii import TermiiGateway
from services.providers import PILOT_GATEWAY, gateway_for_tenant, resolve_gateway


def test_nigerian_pilots_route_to_termii() -> None:
    """AWS refused SMS production access for this account (case
    178663411200756) on billing history, not use case, so SNS cannot serve
    Nigerian farmers. Termii has no sandbox and a registered NG sender ID."""
    for tenant in ("kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "nasarawa", "fct"):
        assert gateway_for_tenant(tenant) == "termii", (
            f"{tenant} should route to Termii — AWS SNS is not available to "
            f"this account and its sandbox needs per-recipient OTP codes"
        )


def test_termii_sender_id_default_matches_the_registered_one() -> None:
    """Termii rejects unregistered sender IDs and carriers will not deliver them.

    The live account registration is "Ecobridge" (active, Nigeria, since
    2026-05-18). The default here was once "EconoBridge" — a different string,
    not registered — which would have failed every farmer send while looking
    like a delivery problem.

    Asserts the FIELD DEFAULT rather than the resolved setting: production
    (ECS) sets no TERMII_SENDER_ID, so the default is what actually ships,
    while a developer's .env may legitimately override it (ours holds
    "N-Alert", Termii's generic shared ID) and must not fail this.
    """
    from config import Settings

    assert Settings.model_fields["termii_sender_id"].default == "Ecobridge"


def test_ecowas_pilots_route_to_twilio() -> None:
    for tenant in ("ghana", "senegal"):
        assert gateway_for_tenant(tenant) == "twilio", (
            f"{tenant} should route to Twilio (international carriers)"
        )


def test_unknown_tenant_raises() -> None:
    with pytest.raises(ValueError):
        gateway_for_tenant("atlantis")


def test_resolve_gateway_falls_back_to_mock_when_unconfigured(monkeypatch) -> None:
    """With no provider keys, every tenant gets the mock rather than failing.

    Env vars take precedence over the .env file in pydantic-settings, so
    setting them forces the unconfigured path even when real values exist
    in .env.
    """
    monkeypatch.setenv("TERMII_API_KEY", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    get_settings.cache_clear()
    try:
        assert isinstance(resolve_gateway("kebbi"), MockGateway)
        assert isinstance(resolve_gateway("ghana"), MockGateway)
    finally:
        get_settings.cache_clear()


def test_resolve_gateway_uses_termii_when_keyed(monkeypatch) -> None:
    """NG tenants get the real Termii gateway once a key is present.

    Guards the failure mode that matters: a missing key silently downgrades to
    MockGateway, which reports status 'mock' and looks like a successful send
    while no farmer receives anything.
    """
    monkeypatch.setenv("TERMII_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    try:
        assert isinstance(resolve_gateway("kebbi"), TermiiGateway)
    finally:
        get_settings.cache_clear()


def test_pilot_gateway_map_covers_all_pilot_tenants() -> None:
    # 10 pilots: 7 NG states (incl. Nasarawa) + FCT + Ghana + Senegal.
    # The provider map must keep parity with services/tenants.py allowlist.
    expected = {
        "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
        "nasarawa", "fct", "ghana", "senegal",
    }
    assert set(PILOT_GATEWAY.keys()) == expected
