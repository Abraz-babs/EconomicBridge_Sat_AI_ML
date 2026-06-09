"""Request/response models for the public Bizra Farms contact form."""
from __future__ import annotations

from pydantic import BaseModel, Field

# Light email shape check — avoids pulling in the email-validator dependency
# that pydantic's EmailStr requires. Good enough to reject obvious garbage; the
# real validation is the operator replying to a live address.
_EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ContactInquiry(BaseModel):
    """A submission from the public Bizra Farms / EconomicBridge contact form."""

    name: str = Field(min_length=1, max_length=120)
    organisation: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=160, pattern=_EMAIL_RE)
    phone: str | None = Field(default=None, max_length=40)
    interest: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=4000)
    # Honeypot — invisible to humans, often auto-filled by bots. A non-empty
    # value means "drop silently" (the router returns success but sends nothing).
    company_website: str | None = Field(default=None, max_length=200)


class ContactAck(BaseModel):
    """Body returned for a received inquiry."""

    received: bool
