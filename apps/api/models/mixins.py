"""Shared column mixins.

Per ARCHITECTURE.md §8, every business table carries the same set of audit
columns. Mixins let the model files stay short and consistent.
"""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """UUID PK with server-side default of uuid_generate_v4()."""

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid4,
    )


class TimestampMixin:
    """Standard created_at / updated_at columns with server-side defaults.

    Note: updated_at auto-bumping is handled by the `update_updated_at` Postgres
    trigger created in init_db.sql, not by SQLAlchemy's onupdate. This keeps the
    timestamp authoritative even for raw SQL updates.
    """

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
