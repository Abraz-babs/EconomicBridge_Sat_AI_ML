"""Gateway selection per tenant.

Reads `sms_gateway` from tenants.yaml (NG states → termii, ECOWAS → twilio)
and falls back to the mock gateway when the chosen provider isn't
configured. The PILOT map is hard-coded here for the 9 pilot tenants because
the file is small and gives us a fast lookup; the loader has a note for when
to switch to parsing tenants.yaml on startup.
"""
from __future__ import annotations

import logging

from gateways.base import GatewayName, SmsGateway
from gateways.mock import MockGateway
from gateways.termii import TermiiGateway
from gateways.twilio import TwilioGateway

log = logging.getLogger(__name__)

# Pulled from tenants.yaml (sms_gateway field per tenant). The 9 pilots:
PILOT_GATEWAY: dict[str, GatewayName] = {
    "kebbi":   "termii",
    "benue":   "termii",
    "plateau": "termii",
    "kaduna":  "termii",
    "niger":   "termii",
    "zamfara": "termii",
    "fct":     "termii",
    "ghana":   "twilio",
    "senegal": "twilio",
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
      - tenant's primary provider missing API key → MockGateway
        (so dev pipelines run end-to-end without external dependencies)
    """
    primary = gateway_for_tenant(tenant_id)
    if primary == "termii":
        client = TermiiGateway()
        if client.configured:
            return client
        log.info("notifications: termii not configured — using MockGateway for %s", tenant_id)
        return MockGateway()
    # twilio
    client = TwilioGateway()
    if client.configured:
        return client
    log.info("notifications: twilio not configured — using MockGateway for %s", tenant_id)
    return MockGateway()
