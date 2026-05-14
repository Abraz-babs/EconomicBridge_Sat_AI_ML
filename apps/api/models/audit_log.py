"""Audit log model — append-only.

INSERT-only at the DB level via the `audit_log_no_update` / `audit_log_no_delete`
rules created in the migration. The application user has SELECT+INSERT only —
no UPDATE/DELETE grants — see CLAUDE.md §4.6.

Optionally converted to a TimescaleDB hypertable in the migration (only if the
`timescaledb` extension is installed). Without it the table is a plain
time-indexed B-tree table.
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


from db.base import Base


class AuditLog(Base):
    """Immutable audit record. Captured on every mutating request."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), index=True
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)

    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_schema: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    data_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    query_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="INFO")
    extra: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
