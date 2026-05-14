"""Organisation model.

An organisation is the entity that signs the Data Processing Agreement (DPA) and
owns one or more users. Tenant access is encoded in `permitted_tenants` — a list
of tenant IDs like `kebbi`, `ghana`. Cross-border queries require the target
tenant to appear in `bilateral_agreements` (CLAUDE.md §4.2).
"""
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Organisation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """NGO, government, international body, or research institution."""

    __tablename__ = "organisations"

    org_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # ngo|gov|intl|research
    country_iso: Mapped[str | None] = mapped_column(String(3), nullable=True)

    permitted_tenants: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    bilateral_agreements: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )

    dpa_signed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dpa_signed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    dpa_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
