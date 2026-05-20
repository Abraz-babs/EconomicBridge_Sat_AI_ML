"""create public.imagery_downloads (Sentinel SAFE bundle catalogue)

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-20

Slice 3a — Phase A.6 substrate. Every Sentinel-1/2 (or future
Sentinel-3) SAFE bundle the ingestion service streams from CDSE
lands in an S3 bucket under a tenant-prefixed key (CLAUDE.md §4.2).
This table is the catalogue: which scene, which tenant, which key,
what size, when, errors.

Lives in `public` (not per-tenant) because the operator team may need
to do cross-tenant queries — e.g. "how many GB did we download last
week across all states?". Tenant isolation for queries is enforced at
the application layer via the tenant_id column (CLAUDE.md §4.2).

INSERT-mostly: every download attempt writes one row. Updates happen
only to set download_completed_at + size_bytes + sha256 on success, or
error_message on failure.

Idempotency: UNIQUE (tenant_id, scene_id) — same scene re-requested for
the same tenant returns the existing row instead of re-downloading.
The application checks this before kicking off the stream.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.imagery_downloads (
            id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                VARCHAR(50)  NOT NULL,
            scene_id                 TEXT         NOT NULL,
            collection               VARCHAR(50)  NOT NULL,

            s3_bucket                VARCHAR(120) NOT NULL,
            s3_key                   TEXT         NOT NULL,

            captured_at              TIMESTAMPTZ,
            size_bytes               BIGINT,
            sha256                   VARCHAR(64),

            download_started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            download_completed_at    TIMESTAMPTZ,
            status                   VARCHAR(20) NOT NULL DEFAULT 'in_progress',
            error_message            TEXT,

            trace_id                 UUID,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_imagery_downloads_status
                CHECK (status IN ('in_progress', 'succeeded', 'failed', 'mocked')),
            CONSTRAINT uq_imagery_downloads_scene
                UNIQUE (tenant_id, scene_id)
        )
        """
    )

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_imagery_downloads_tenant_status "
        "ON public.imagery_downloads (tenant_id, status, captured_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_imagery_downloads_collection "
        "ON public.imagery_downloads (collection, captured_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_imagery_downloads_in_progress "
        "ON public.imagery_downloads (download_started_at) "
        "WHERE status = 'in_progress'",
    ):
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.imagery_downloads")
