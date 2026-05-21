"""create aid_agencies registry + per-tenant aid_coverage (Slice 02.real)

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-21

Module 02 — Aid Coordination Bridge. Two tables:

  public.aid_agencies (cross-tenant registry)
    Same WFP/UNHCR/NEMA/etc. agency exists once globally — the
    sector + name + identifying slug are not per-tenant.

  tenant_<id>.aid_coverage (per-tenant operational records)
    One row per (agency, LGA) the agency operates in for this
    tenant ROI. Carries beneficiary counts + last-active timestamp
    + source (`seed_v1` initially; `wfp_scope_v1`, `unhcr_progres_v1`,
    `nema_v1`, `manual_admin` once live ingestion lands).

agency_slug is a plain VARCHAR join key — no cross-schema foreign
key, since `tenant_<id>.aid_coverage` lives in a per-tenant schema
and `public.aid_agencies` lives in `public`. The API joins by slug
at read time.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants on this
migration so we don't have to chase nasarawa later.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_aid_coverage_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".aid_coverage (
            id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id             VARCHAR(50) NOT NULL,

            -- Agency reference (joins to public.aid_agencies.slug at
            -- read time; no cross-schema FK).
            agency_slug           VARCHAR(40) NOT NULL,

            -- LGA / district covered by this agency in this tenant
            lga                   TEXT NOT NULL,

            -- Operational metrics
            beneficiaries_served  INTEGER NOT NULL DEFAULT 0
                CHECK (beneficiaries_served >= 0),
            last_active_at        DATE,

            -- Audit
            source                VARCHAR(40) NOT NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- One row per (agency, LGA, source) — repeat-imports from
            -- the same upload replace; cross-source rows coexist for audit.
            CONSTRAINT uq_{tenant}_aid_coverage_agency_lga
                UNIQUE (agency_slug, lga, source)
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_aid_coverage_agency '
        f'ON "{schema}".aid_coverage (agency_slug)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_aid_coverage_lga '
        f'ON "{schema}".aid_coverage (lga)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_aid_coverage_source '
        f'ON "{schema}".aid_coverage (source, updated_at DESC)'
    )


def _drop_aid_coverage_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".aid_coverage CASCADE')


def upgrade() -> None:
    # Global agency registry — small, cross-tenant.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.aid_agencies (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            slug        VARCHAR(40) NOT NULL UNIQUE,
            name        VARCHAR(120) NOT NULL,
            sector      VARCHAR(60) NOT NULL,
            country     VARCHAR(40),    -- 'international' | 'nigeria' | etc.
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_aid_agencies_sector "
        "ON public.aid_agencies (sector)"
    )

    for tenant in PILOT_TENANTS:
        _create_aid_coverage_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_aid_coverage_for(tenant)
    op.execute("DROP TABLE IF EXISTS public.aid_agencies CASCADE")
