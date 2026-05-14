"""Create users and audit_log tables

Revision ID: 001
Revises: None
Create Date: 2026-03-11

Initial migration creating the foundational tables required by every tenant:
- users: Authentication and authorization
- audit_log: INSERT-only compliance log (NDPA 2023)

These tables are created within each tenant's schema.
The search_path is set by the migration runner (scripts/run_migrations.py).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET


# Revision identifiers
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create users and audit_log tables."""
    # ─────────────────────────────────────
    # USERS TABLE
    # ─────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.String(50),
            nullable=False,
            server_default="viewer",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", "tenant_id", name="uq_users_email_tenant"),
    )

    # Users indexes
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_tenant_id", "users", ["tenant_id"])
    op.create_index("idx_users_role", "users", ["role"])

    # ─────────────────────────────────────
    # AUDIT LOG TABLE (INSERT-only)
    # ─────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column(
            "trace_id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Audit log indexes
    op.create_index("idx_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("idx_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])
    op.create_index("idx_audit_log_trace_id", "audit_log", ["trace_id"])

    # Action CHECK constraint
    op.execute(
        """
        ALTER TABLE audit_log ADD CONSTRAINT chk_audit_log_action
        CHECK (action IN (
            'CREATE', 'READ', 'UPDATE', 'DELETE',
            'EXPORT', 'LOGIN', 'LOGOUT', 'PERMISSION_CHANGE'
        ))
        """
    )


def downgrade() -> None:
    """Drop users and audit_log tables."""
    op.drop_table("audit_log")
    op.drop_table("users")
