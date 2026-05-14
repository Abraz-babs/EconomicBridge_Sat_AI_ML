"""Refresh-token registry.

Stores SHA-256 hashes of issued refresh tokens so individual sessions can be
revoked without invalidating every JWT. Raw tokens are NEVER stored — only the
hash. CLAUDE.md §4.1.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.mixins import UUIDPrimaryKeyMixin


class RefreshToken(Base, UUIDPrimaryKeyMixin):
    """One row per issued refresh token. Hash-only, revocable."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # refresh_tokens has only created_at — no updated_at (tokens are never edited,
    # only revoked, and revoked_at carries that timestamp).
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default="now()",
    )
