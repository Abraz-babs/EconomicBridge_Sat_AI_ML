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


def send_report_email(
    *, to: str, tenant_name: str, module_label: str, period: str,
    pdf: bytes, filename: str,
) -> bool:
    """Email a generated report PDF (scheduled reports). Returns True if a real
    send was accepted. Console backend logs a stub (no attachment in dev)."""
    s = get_settings()
    subject = f"EconomicBridge — {module_label} report · {tenant_name} ({period})"
    body = (
        f"Attached is your scheduled {module_label} report for {tenant_name}, "
        f"covering {period}.\n\n— EconomicBridge (operated by Bizra Farms "
        f"Integrated Nigeria Ltd)\n"
    )
    if s.email_backend == "ses":
        return _send_ses_with_attachment(
            to=to, subject=subject, body=body, pdf=pdf, filename=filename,
        )
    logger.info(
        "[email:console] report to=%s subject=%r (%d-byte PDF '%s' — not sent in dev)",
        to, subject, len(pdf), filename,
    )
    return False


def _send_ses_with_attachment(
    *, to: str, subject: str, body: str, pdf: bytes, filename: str,
) -> bool:
    s = get_settings()
    try:
        import boto3
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = s.email_from
        msg["To"] = to
        msg.attach(MIMEText(body))
        part = MIMEApplication(pdf, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

        client = boto3.client("ses", region_name=s.aws_region)
        client.send_raw_email(
            Source=s.email_from, Destinations=[to],
            RawMessage={"Data": msg.as_string()},
        )
        return True
    except Exception as exc:  # noqa: BLE001 — never let a send failure crash the job
        logger.warning("[email:ses] report to %s failed: %s", to, exc)
        return False
