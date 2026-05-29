"""Gateway selection per tenant.

NG states → AWS SNS (replaced Termii), ECOWAS → Twilio; falls back to the
mock gateway when the chosen provider isn't configured. The PILOT map is
hard-coded here for the 10 pilot tenants because the file is small and gives
us a fast lookup; the loader has a note for when to switch to parsing
tenants.yaml on startup.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from gateways.base import GatewayName, SmsGateway
from gateways.mock import MockGateway
from gateways.sns import SnsGateway
from gateways.termii import TermiiGateway
from gateways.twilio import TwilioGateway

log = logging.getLogger(__name__)

# Per-tenant primary provider. Nigerian states moved termii → sns (AWS-native
# SMS); ECOWAS stays on Twilio.
PILOT_GATEWAY: dict[str, GatewayName] = {
    "kebbi":    "sns",
    "benue":    "sns",
    "plateau":  "sns",
    "kaduna":   "sns",
    "niger":    "sns",
    "zamfara":  "sns",
    "nasarawa": "sns",
    "fct":      "sns",
    "ghana":    "twilio",
    "senegal":  "twilio",
}

# Gateway name → constructor. Termii is retained as a still-valid option even
# though no pilot routes to it now (so a tenant can be switched back without
# code changes).
_CONSTRUCTORS: dict[GatewayName, Callable[[], SmsGateway]] = {
    "sns": SnsGateway,
    "twilio": TwilioGateway,
    "termii": TermiiGateway,
    "mock": MockGateway,
}


def gateway_for_tenant(tenant_id: str) -> GatewayName:
    """Return the configured provider for `tenant_id` (closed enum)."""
    try:
        return PILOT_GATEWAY[tenant_id]
    except KeyError as exc:
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}") from exc


def resolve_gateway(tenant_id: str) -> SmsGateway:
    """Pick the live gateway for a tenant, falling back to MockGateway in dev.

    The fallback policy:
      - tenant's primary provider configured → use it
      - tenant's primary provider not configured → MockGateway
        (so dev pipelines run end-to-end without external dependencies)
    """
    primary = gateway_for_tenant(tenant_id)
    client = _CONSTRUCTORS[primary]()
    if getattr(client, "configured", True):
        return client
    log.info(
        "notifications: %s not configured — using MockGateway for %s",
        primary, tenant_id,
    )
    return MockGateway()
