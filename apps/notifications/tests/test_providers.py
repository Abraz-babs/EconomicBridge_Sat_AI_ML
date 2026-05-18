"""Unit tests for the tenant→gateway selector + mock fallback."""
from __future__ import annotations

import pytest

from gateways.mock import MockGateway
from services.providers import PILOT_GATEWAY, gateway_for_tenant, resolve_gateway


def test_nigerian_pilots_route_to_termii() -> None:
    for tenant in ("kebbi", "benue", "plateau", "kaduna", "niger", "zamfara", "nasarawa", "fct"):
        assert gateway_for_tenant(tenant) == "termii", (
            f"{tenant} should route to Termii (Nigerian carriers)"
        )


def test_ecowas_pilots_route_to_twilio() -> None:
    for tenant in ("ghana", "senegal"):
        assert gateway_for_tenant(tenant) == "twilio", (
            f"{tenant} should route to Twilio (international carriers)"
        )


def test_unknown_tenant_raises() -> None:
    with pytest.raises(ValueError):
        gateway_for_tenant("atlantis")


def test_resolve_gateway_falls_back_to_mock_when_unconfigured(monkeypatch) -> None:
    """With no Termii/Twilio keys configured, every tenant gets the mock.

    Env vars take precedence over the .env file in pydantic-settings, so
    setting them to empty strings forces the unconfigured path even when
    real keys are present in .env.
    """
    monkeypatch.setenv("TERMII_API_KEY", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    from config import get_settings
    get_settings.cache_clear()
    try:
        gw = resolve_gateway("kebbi")
        assert isinstance(gw, MockGateway)
        gw2 = resolve_gateway("ghana")
        assert isinstance(gw2, MockGateway)
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
