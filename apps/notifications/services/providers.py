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

# Per-tenant primary provider. Nigerian states are back on Termii; ECOWAS stays
# on Twilio.
#
# WHY NOT SNS (2026-08-17). The NG tenants were moved termii → sns for
# AWS-native delivery. AWS then refused SMS production access outright:
#
#   "Due to some limiting factors on your account at this time, you are not
#    eligible to send SMS messages in EU (Ireland) region. You will need to
#    show a pattern of use of other AWS services and a consistent paid billing
#    history."   — case 178663411200756
#
# That is an ACCOUNT-STANDING decision, not a use-case one: the account runs on
# Activate credits, so AWS sees no paid billing history. No amount of
# re-explaining farmer advisories changes it, and it cannot be cleared for
# months. Meanwhile SNS kept us in the sandbox: a $1/month cap and a maximum of
# 10 destinations, each needing the RECIPIENT to read back a one-time code —
# unworkable for smallholder farmers who are in fields, off-network, and whose
# codes expire.
#
# Termii clears all three problems at once and was already provisioned:
#   * no sandbox, so no per-farmer verification codes at all
#   * sender ID "Ecobridge" REGISTERED and active for Nigeria since 2026-05-18,
#     which AWS offers no self-service route for (75 registration types, none
#     for NG)
#   * measured SNS cost was USD 0.357 per single-segment message to MTN
#     (delivery receipt, not a price list); Termii bills single-digit naira
#
# Do not move these back to SNS without checking the account is out of the SMS
# sandbox AND that a Nigerian sender ID is registered. Both were assumed once.
PILOT_GATEWAY: dict[str, GatewayName] = {
    "kebbi":    "termii",
    "benue":    "termii",
    "plateau":  "termii",
    "kaduna":   "termii",
    "niger":    "termii",
    "zamfara":  "termii",
    "nasarawa": "termii",
    "fct":      "termii",
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
