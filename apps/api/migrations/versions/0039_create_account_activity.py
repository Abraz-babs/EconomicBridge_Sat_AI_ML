"""Per-account activity tracking: daily usage rollup + login history.

Why a new table instead of `public.audit_log`:

`audit_log` is the compliance record — INSERT-only, one row per *mutating*
request (CLAUDE.md §4.6). Partner and government accounts almost never mutate;
they read. So the audit log is structurally blind to how an account actually
uses the platform, and widening it to every GET would turn a legal record into
a request firehose (a single dashboard session issues dozens of polls).

`account_activity` is therefore a **daily rollup**, not a log: one row per
(user, day, tenant, module) with a counter. A busy account produces on the
order of ten rows a day rather than thousands, and the answers an operator
actually wants — who is using the platform, which modules, how often, when
were they last seen — are single-index scans.

`account_login` stays row-per-event because logins are low-volume and the
history itself is the useful artefact (session cadence, source IP).

Revision ID: 0039
Revises: 0038
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: Union[str, Sequence[str], None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── account_activity (daily rollup, UPSERT target) ────────────────────
    op.create_table(
        "account_activity",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        # Empty string, not NULL: it is part of the primary key, and NULL would
        # defeat ON CONFLICT (NULL is never equal to NULL in a unique index),
        # silently inserting a duplicate row on every single flush.
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default=""),
        sa.Column("module", sa.String(50), nullable=False, server_default=""),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id", "day", "tenant_id", "module",
                                name="pk_account_activity"),
        schema="public",
    )
    op.create_index("ix_account_activity_day", "account_activity",
                    [sa.text("day DESC")], schema="public")
    op.create_index("ix_account_activity_org", "account_activity",
                    ["org_id"], schema="public")

    # ─── account_login (row per event) ─────────────────────────────────────
    op.create_table(
        "account_login",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        schema="public",
    )
    op.create_index("ix_account_login_user_at", "account_login",
                    ["user_id", sa.text("at DESC")], schema="public")


def downgrade() -> None:
    op.drop_index("ix_account_login_user_at", "account_login", schema="public")
    op.drop_table("account_login", schema="public")
    op.drop_index("ix_account_activity_org", "account_activity", schema="public")
    op.drop_index("ix_account_activity_day", "account_activity", schema="public")
    op.drop_table("account_activity", schema="public")
