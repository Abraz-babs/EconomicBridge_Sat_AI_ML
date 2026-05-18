"""create data_processing_agreements + data_subject_requests

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-18

Step 11 — compliance close-out for Q1 2026.

Two new tables in the `public` schema (cross-tenant by design, owned by the
platform operator rather than any individual pilot):

* `data_processing_agreements`  — one row per Organisation x Tenant scope. A
  DPA must exist with status='signed' (and not yet expired) before that
  organisation can be served PII-bearing endpoints for that tenant. The
  audit middleware will read this table going forward; for Step 11 we lay
  down the schema + CRUD so the operator can register agreements.

* `data_subject_requests`       — one row per NDPA-2023 / GDPR / ECOWAS-equiv
  data-subject right exercised (access, rectification, erasure, portability,
  objection). Tracked centrally because subjects may have data across
  multiple tenants. Status transitions: received -> in_review -> fulfilled
  | rejected.

INSERT-only is NOT used here — both tables intentionally allow UPDATE for
lifecycle transitions (DPA gets signed, DSR gets fulfilled). The audit_log
still captures every change.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── data_processing_agreements ─────────────────────────────────────
    op.create_table(
        "data_processing_agreements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("agreement_type", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("signatory_name", sa.Text(), nullable=True),
        sa.Column("signatory_email", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scope",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("document_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "agreement_type IN ('mou', 'dpa', 'bilateral', 'research')",
            name="chk_dpa_agreement_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'signed', 'expired', 'revoked')",
            name="chk_dpa_status",
        ),
    )
    op.create_index(
        "ix_dpa_org_tenant", "data_processing_agreements", ["organisation_id", "tenant_id"],
    )
    op.create_index(
        "ix_dpa_status_expires",
        "data_processing_agreements",
        ["status", "expires_at"],
    )
    # Hot-path index: the auth/middleware layer will ask "is there a signed,
    # non-expired DPA for (org, tenant)?" thousands of times a day.
    op.execute(
        "CREATE INDEX ix_dpa_active "
        "ON data_processing_agreements (organisation_id, tenant_id) "
        "WHERE status = 'signed'"
    )
    op.execute(
        "CREATE TRIGGER trg_dpa_updated_at "
        "BEFORE UPDATE ON data_processing_agreements "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── data_subject_requests ──────────────────────────────────────────
    op.create_table(
        "data_subject_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("tenant_id", sa.String(50), nullable=True),
        sa.Column("subject_phone_e164", sa.String(20), nullable=True),
        sa.Column("subject_email", sa.Text(), nullable=True),
        sa.Column("subject_full_name", sa.Text(), nullable=True),
        sa.Column("request_type", sa.String(20), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'received'"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requester_notes", sa.Text(), nullable=True),
        sa.Column("handler_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "request_type IN ('access', 'rectification', 'erasure', 'portability', 'objection')",
            name="chk_dsr_request_type",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'in_review', 'fulfilled', 'rejected')",
            name="chk_dsr_status",
        ),
        sa.CheckConstraint(
            "subject_phone_e164 IS NOT NULL OR subject_email IS NOT NULL",
            name="chk_dsr_has_contact",
        ),
    )
    op.create_index("ix_dsr_status", "data_subject_requests", ["status", "received_at"])
    op.create_index("ix_dsr_phone", "data_subject_requests", ["subject_phone_e164"])
    op.create_index("ix_dsr_email", "data_subject_requests", ["subject_email"])
    op.execute(
        "CREATE TRIGGER trg_dsr_updated_at "
        "BEFORE UPDATE ON data_subject_requests "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_subject_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS data_processing_agreements CASCADE")
