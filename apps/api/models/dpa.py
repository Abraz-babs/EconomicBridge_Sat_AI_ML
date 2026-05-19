"""ORM models for Data Processing Agreements + Data Subject Requests.

Both live in the `public` schema (cross-tenant by design — the operator runs
the compliance layer, not the individual pilots).

* `DataProcessingAgreement` — one row per Organisation × Tenant. A
  `status='signed'` row that's not yet expired must exist before the
  organisation can be served PII-bearing endpoints for that tenant.
* `DataSubjectRequest` — one row per NDPA-2023 / GDPR right-of-subject
  exercised. Status transitions: received → in_review → fulfilled | rejected.

Trigger `update_updated_at()` from migration 0001 keeps `updated_at` fresh.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class DataProcessingAgreement(Base):
    """A signed/pending agreement scoping one organisation to one tenant."""

    __tablename__ = "data_processing_agreements"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    organisation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    agreement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )

    signatory_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    signatory_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scope: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataSubjectRequest(Base):
    """A request from a data subject to exercise their NDPA / GDPR rights."""

    __tablename__ = "data_subject_requests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    tenant_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject_phone_e164: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    subject_email: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    subject_full_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="received"
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requester_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    handler_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
