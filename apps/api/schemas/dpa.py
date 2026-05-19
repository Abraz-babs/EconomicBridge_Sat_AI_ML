"""Pydantic schemas for the DPA + DSR layer.

Mirrors models/dpa.py + the CHECK constraints in migration 0010. The enums
are closed sets — drift between schema and DB would be a runtime bug, so
keep them synced.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field


# ─── Enums (must match migration 0010 CHECK constraints) ───────────────────


class AgreementType(str, Enum):
    MOU = "mou"
    DPA = "dpa"
    BILATERAL = "bilateral"
    RESEARCH = "research"


class AgreementStatus(str, Enum):
    PENDING = "pending"
    SIGNED = "signed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class DsrRequestType(str, Enum):
    ACCESS = "access"
    RECTIFICATION = "rectification"
    ERASURE = "erasure"
    PORTABILITY = "portability"
    OBJECTION = "objection"


class DsrStatus(str, Enum):
    RECEIVED = "received"
    IN_REVIEW = "in_review"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"


# ─── DPA agreement ─────────────────────────────────────────────────────────


class DpaAgreementCreate(BaseModel):
    """POST /api/v1/dpa/agreements body."""

    model_config = ConfigDict(extra="forbid")

    organisation_id: UUID
    tenant_id: Annotated[str, Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]+$")]
    agreement_type: AgreementType
    signatory_name: str | None = Field(default=None, max_length=200)
    signatory_email: EmailStr | None = None
    expires_at: AwareDatetime | None = None
    scope: list[str] = Field(default_factory=list)
    document_url: str | None = Field(default=None, max_length=500)


class DpaAgreementPatch(BaseModel):
    """PATCH /api/v1/dpa/agreements/{id} body — lifecycle + optional fields."""

    model_config = ConfigDict(extra="forbid")

    status: AgreementStatus | None = None
    signatory_name: str | None = Field(default=None, max_length=200)
    signatory_email: EmailStr | None = None
    signed_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    scope: list[str] | None = None
    document_url: str | None = Field(default=None, max_length=500)


class DpaAgreementResponse(BaseModel):
    """A DPA row as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organisation_id: UUID
    tenant_id: str
    agreement_type: AgreementType
    status: AgreementStatus
    signatory_name: str | None
    signatory_email: str | None
    signed_at: AwareDatetime | None
    expires_at: AwareDatetime | None
    scope: list[str]
    document_url: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DpaAgreementListData(BaseModel):
    agreements: list[DpaAgreementResponse]


# ─── DSR (data subject request) ────────────────────────────────────────────


class DsrCreate(BaseModel):
    """POST /api/v1/dpa/data-subject-requests body."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: Annotated[
        str | None,
        Field(default=None, min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]+$"),
    ] = None
    subject_phone_e164: Annotated[
        str | None, Field(default=None, pattern=r"^\+[1-9][0-9]{6,15}$")
    ] = None
    subject_email: EmailStr | None = None
    subject_full_name: str | None = Field(default=None, max_length=200)
    request_type: DsrRequestType
    requester_notes: str | None = Field(default=None, max_length=2000)


class DsrPatch(BaseModel):
    """PATCH /api/v1/dpa/data-subject-requests/{id} — handler updates."""

    model_config = ConfigDict(extra="forbid")

    status: DsrStatus | None = None
    handler_notes: str | None = Field(default=None, max_length=2000)
    fulfilled_at: AwareDatetime | None = None


class DsrResponse(BaseModel):
    """A DSR row as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str | None
    subject_phone_e164: str | None
    subject_email: str | None
    subject_full_name: str | None
    request_type: DsrRequestType
    status: DsrStatus
    received_at: AwareDatetime
    fulfilled_at: AwareDatetime | None
    requester_notes: str | None
    handler_notes: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DsrListData(BaseModel):
    requests: list[DsrResponse]
