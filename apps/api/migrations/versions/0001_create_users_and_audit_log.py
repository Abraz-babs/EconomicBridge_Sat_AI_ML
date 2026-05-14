"""create users + audit log baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-12

Creates the public-schema tables that exist for every deployment regardless of
tenant: organisations, users, refresh_tokens, audit_log. Matches the design in
scripts/init_db.sql so a fresh `alembic upgrade head` produces an equivalent DB.

Notes
-----
* Extensions are created `IF NOT EXISTS` so this is safe to re-run on a partially
  initialised DB.
* `timescaledb` is optional — the hypertable conversion is wrapped in a DO block
  that no-ops if the extension is missing. The table itself is still time-indexed
  via a regular B-tree.
* `audit_log` has INSERT-only enforcement via two RULES — UPDATE and DELETE are
  silently rewritten to NOTHING (CLAUDE.md §4.6).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── Extensions ────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # PostGIS / TimescaleDB are best-effort — they may not be installed in dev.
    op.execute("""
        DO $$
        BEGIN
            BEGIN
                CREATE EXTENSION IF NOT EXISTS postgis;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'postgis extension unavailable — skipping';
            END;
            BEGIN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'timescaledb extension unavailable — skipping';
            END;
        END
        $$
    """)

    # ─── updated_at trigger function ───────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # ─── organisations ─────────────────────────────────────────────────────
    op.create_table(
        "organisations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("org_id", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("country_iso", sa.String(3), nullable=True),
        sa.Column(
            "permitted_tenants",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "bilateral_agreements",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("dpa_signed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dpa_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_organisations_org_id", "organisations", ["org_id"], unique=True)
    op.execute(
        "CREATE TRIGGER trg_organisations_updated_at "
        "BEFORE UPDATE ON organisations FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ─── users ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="ngo"),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("language", sa.String(5), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.execute(
        "CREATE TRIGGER trg_users_updated_at "
        "BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ─── refresh_tokens ────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # ─── audit_log (INSERT-only) ───────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tenant_schema", sa.String(100), nullable=True),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("data_type", sa.String(100), nullable=True),
        sa.Column("query_hash", sa.String(32), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", [sa.text("timestamp DESC")])
    op.create_index("ix_audit_log_tenant", "audit_log", ["tenant_schema"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_trace", "audit_log", ["trace_id"])
    op.create_index(
        "ix_audit_log_severity",
        "audit_log",
        ["severity"],
        postgresql_where=sa.text("severity IN ('WARNING', 'ERROR', 'CRITICAL')"),
    )

    # INSERT-only at the DB level (CLAUDE.md §4.6).
    op.execute("CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING")
    op.execute("CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING")

    # Optional TimescaleDB hypertable — only if the extension is available.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'audit_log',
                    'timestamp',
                    if_not_exists => TRUE,
                    chunk_time_interval => INTERVAL '7 days'
                );
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TABLE IF EXISTS organisations CASCADE")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at() CASCADE")
