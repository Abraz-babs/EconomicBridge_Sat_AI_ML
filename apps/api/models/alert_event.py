"""Per-tenant alert event ORM model.

Lives in the tenant_<id>.alert_events table. The mapping deliberately does NOT
declare a `schema=` in `__table_args__` — every query is implicitly scoped by
the session's `search_path`, which is set by db.engine.get_session reading
`request.state.tenant_id` (Step 6). This means:

* querying without a tenant context fails fast (no public.alert_events table)
* there is structurally no way to leak across tenants by accident — you cannot
  forget to pass a tenant_id when the table itself does not exist in public

The column shape mirrors the contract in CLAUDE.md §9 (ModelPrediction) and the
legacy bootstrap design in scripts/init_db.sql's create_tenant_schema(). PostGIS
geometry columns require the `postgis` extension (installed via the EDB Stack
Builder during Step 4).
"""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import ARRAY, Boolean, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AlertEvent(Base):
    """A single conflict / flood / crop / drought alert raised by an ML model."""

    __tablename__ = "alert_events"
    # `is_tenant_scoped` is read by migrations/env.py's `include_object` hook so
    # Alembic autogenerate skips this table (it lives in per-tenant schemas, not
    # public). DDL is hand-written in 0003_create_alert_events.py.
    __table_args__ = {"info": {"is_tenant_scoped": True}}

    # ── Identity ────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── Classification ──────────────────────────────────────────────────
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="pending_review"
    )

    # ── Where ───────────────────────────────────────────────────────────
    zone_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    lga: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    boundary: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )

    # ── ML / detection ──────────────────────────────────────────────────
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    affected_area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    livelihoods_at_risk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    economic_value_ngn: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_breach_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    satellite_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    satellite_pass_time: Mapped[datetime | None] = mapped_column(nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shap_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ── Review pipeline ─────────────────────────────────────────────────
    human_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    agencies_notified: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )

    # ── Audit columns ───────────────────────────────────────────────────
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"<AlertEvent id={self.id} tenant={self.tenant_id} "
            f"type={self.alert_type} severity={self.severity} status={self.status}>"
        )
