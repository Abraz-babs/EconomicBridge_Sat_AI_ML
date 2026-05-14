"""create ingestion_runs + per-tenant heat_signatures

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-14

Adds the first satellite-data pipeline tables.

* `public.ingestion_runs` — cross-tenant audit log of every ingestion job
  (manual or scheduled). One row per (source, tenant, window). Records the
  outcome so operators can answer "did FIRMS run for Kebbi today?".

* `tenant_<id>.heat_signatures` — one row per fire pixel detected by NASA
  FIRMS (MODIS / VIIRS). Lives in per-tenant schemas because the data is
  derived from the tenant's ROI bounding box. Indexed for spatial range
  queries (GIST) and time-range scans (B-tree).

Both run as part of the satellite ingestion microservice (apps/ingestion).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal",
)


def _create_heat_signatures_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".heat_signatures (
            id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id           VARCHAR(50) NOT NULL,

            source              VARCHAR(50) NOT NULL,
            satellite           VARCHAR(30),
            instrument          VARCHAR(30),

            detected_at         TIMESTAMPTZ NOT NULL,
            location            GEOMETRY(POINT, 4326) NOT NULL,

            brightness_k        DOUBLE PRECISION,
            bright_t31_k        DOUBLE PRECISION,
            scan                DOUBLE PRECISION,
            track               DOUBLE PRECISION,
            frp                 DOUBLE PRECISION,
            confidence          VARCHAR(20),
            daynight            CHAR(1),

            ingestion_run_id    UUID,
            raw_payload         JSONB,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_heat_daynight
                CHECK (daynight IS NULL OR daynight IN ('D', 'N'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_heat_detected_at '
        f'ON "{schema}".heat_signatures (detected_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_heat_source '
        f'ON "{schema}".heat_signatures (source)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_heat_location '
        f'ON "{schema}".heat_signatures USING GIST (location)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_heat_run '
        f'ON "{schema}".heat_signatures (ingestion_run_id)'
    )


def _drop_heat_signatures_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".heat_signatures CASCADE')


def upgrade() -> None:
    # ── public.ingestion_runs ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.ingestion_runs (
            id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

            source              VARCHAR(50) NOT NULL,
            tenant_id           VARCHAR(50) NOT NULL,
            trigger             VARCHAR(20) NOT NULL,

            window_start        TIMESTAMPTZ,
            window_end          TIMESTAMPTZ,

            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at         TIMESTAMPTZ,
            duration_ms         INTEGER,

            status              VARCHAR(20) NOT NULL DEFAULT 'running',
            records_ingested    INTEGER NOT NULL DEFAULT 0,
            error_message       TEXT,

            trace_id            UUID,
            dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,

            CONSTRAINT chk_ingestion_runs_status
                CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
            CONSTRAINT chk_ingestion_runs_trigger
                CHECK (trigger IN ('manual', 'scheduled', 'backfill'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started "
        "ON public.ingestion_runs (started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_tenant "
        "ON public.ingestion_runs (source, tenant_id, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status "
        "ON public.ingestion_runs (status) WHERE status IN ('failed', 'running')"
    )

    # ── tenant_<id>.heat_signatures ────────────────────────────────────
    for tenant in PILOT_TENANTS:
        _create_heat_signatures_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_heat_signatures_for(tenant)
    op.execute("DROP TABLE IF EXISTS public.ingestion_runs CASCADE")
