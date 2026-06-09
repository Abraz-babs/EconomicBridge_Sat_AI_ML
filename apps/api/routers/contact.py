"""Public contact-form endpoint — POST /api/v1/contact.

No auth, no tenant. Emails each inquiry to the operator inbox
(settings.contact_recipient_email) via SES — console-logged in dev. Spam is
mitigated with a per-IP submission window plus a honeypot field; production
should ALSO rate-limit at the gateway/WAF (CLAUDE.md §4.1).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status

from schemas.contact import ContactAck, ContactInquiry
from schemas.envelope import ResponseMeta, SuccessResponse
from services.email import send_contact_inquiry

router = APIRouter(prefix="/contact", tags=["contact"])

# Per-process, IP-keyed sliding window of accepted submissions. Defence-in-depth,
# not distributed — same rationale as core/ratelimit for logins.
_MAX_PER_WINDOW = 3
_WINDOW_SECONDS = 600  # 10 minutes
_submissions: dict[str, list[float]] = {}


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(key: str) -> bool:
    """True when this IP has already hit the window cap; records the hit otherwise."""
    now = time.time()
    recent = [t for t in _submissions.get(key, []) if now - t < _WINDOW_SECONDS]
    if len(recent) >= _MAX_PER_WINDOW:
        _submissions[key] = recent
        return True
    _submissions[key] = recent + [now]
    return False


def _ack(trace_id: UUID) -> SuccessResponse[ContactAck]:
    return SuccessResponse(
        data=ContactAck(received=True),
        meta=ResponseMeta(
            tenant_id=None,
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc),
            pagination=None,
        ),
    )


@router.post("", response_model=SuccessResponse[ContactAck])
async def submit_contact(
    request: Request, inquiry: ContactInquiry,
) -> SuccessResponse[ContactAck]:
    """Receive a public contact inquiry and email it to the operator inbox."""
    trace_id: UUID = getattr(request.state, "trace_id", uuid4())

    # Honeypot tripped → looks like a bot. Acknowledge but send nothing, and
    # don't spend a rate-limit slot on it.
    if inquiry.company_website:
        return _ack(trace_id)

    if _rate_limited(_client_key(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many inquiries from this address. Please try again shortly.",
        )

    # Best-effort (mirrors invite email): a send failure must not 500 the form.
    send_contact_inquiry(
        name=inquiry.name,
        organisation=inquiry.organisation,
        email=inquiry.email,
        phone=inquiry.phone,
        interest=inquiry.interest,
        region=inquiry.region,
        message=inquiry.message,
    )
    return _ack(trace_id)
