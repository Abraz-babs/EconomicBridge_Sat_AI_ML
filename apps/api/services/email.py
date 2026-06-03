"""Outbound email — invite/activation messages.

Pluggable backend, mirroring the SMS gateway pattern:
  * 'console' (dev default) — logs the message + link and returns False for
    "really sent". No spend, no infra. The router echoes the activation link in
    the API response so the operator can copy it.
  * 'ses' (prod) — sends via AWS SES (boto3). Requires a verified sender and
    `aws_region` set. Returns True on accept.

Selected by `settings.email_backend`. Never raises on a send failure — onboarding
must not roll back just because email is down; the link is logged regardless.
"""
from __future__ import annotations

import logging

from config import get_settings

logger = logging.getLogger(__name__)


def _invite_body(tenant_name: str, activate_url: str) -> tuple[str, str]:
    subject = "Activate your EconomicBridge account"
    body = (
        f"Hello,\n\n"
        f"An EconomicBridge account has been created for {tenant_name}.\n"
        f"Set your password and activate your account using the link below "
        f"(valid for {get_settings().invite_ttl_hours} hours):\n\n"
        f"  {activate_url}\n\n"
        f"If you weren't expecting this, you can ignore this email.\n\n"
        f"— EconomicBridge (operated by Bizra Farms Integrated Nigeria Ltd)\n"
    )
    return subject, body


def send_invite_email(*, to: str, tenant_name: str, activate_url: str) -> bool:
    """Send an activation invite. Returns True if a real send was accepted."""
    s = get_settings()
    subject, body = _invite_body(tenant_name, activate_url)

    if s.email_backend == "ses":
        return _send_ses(to=to, subject=subject, body=body)

    # console (dev): log everything, including the link, so it can be tested.
    logger.info(
        "[email:console] to=%s subject=%r\n%s", to, subject, body,
    )
    return False


def _send_ses(*, to: str, subject: str, body: str) -> bool:
    s = get_settings()
    try:
        import boto3  # imported lazily so dev never needs boto3 configured

        client = boto3.client("ses", region_name=s.aws_region)
        client.send_email(
            Source=s.email_from,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — email failure must not break onboarding
        logger.warning("[email:ses] send to %s failed: %s", to, exc)
        return False
