"""create per-tenant farm_checks table (CropGuard Farm Check records)

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-28

Each saved Farm Check is one field observation: a coordinate + crop the
operator checked, plus the satellite reading that came back (latest-usable
Sentinel-2 NDVI health verdict, Sentinel-1 SAR, and the per-plot stress
early-warning). Mirrors how crop_predictions (migration 0014) records each
leaf-photo diagnosis — so both CropGuard tiers (satellite + leaf) keep a
recallable, place-tagged history.

The headline reading lives in typed columns (for filtering/aggregation); the
full result — NDVI trend, every usable pass, the note — rides in `detail`
JSONB so a recalled record reproduces the original verdict faithfully.

Per-tenant schema (CLAUDE.md §4.2). All 10 pilot tenants get the table here;
new tenants inherit it via services/tenant_provision.py (LIKE … INCLUDING ALL).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, Sequence[str], None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_farm_checks_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".farm_checks (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id               VARCHAR(50) NOT NULL,

            -- Where + what was checked (the record tags)
            location                GEOMETRY(POINT, 4326) NOT NULL,
            lat                     DOUBLE PRECISION NOT NULL,
            lon                     DOUBLE PRECISION NOT NULL,
            crop                    TEXT NOT NULL,
            lga                     TEXT,

            -- Sentinel-2 NDVI health reading (latest usable pass)
            ndvi                    DOUBLE PRECISION,
            ndvi_date               DATE,
            health                  VARCHAR(20) NOT NULL,
            verdict                 TEXT NOT NULL DEFAULT '',

            -- Sentinel-1 SAR (all-weather backstop)
            sar_db                  DOUBLE PRECISION,
            sar_date                DATE,

            -- Per-plot vegetation-stress early-warning
            stress_level            VARCHAR(20),
            stress_z                DOUBLE PRECISION,
            stress_message          TEXT,

            -- Footprint
            sample_count            INTEGER NOT NULL DEFAULT 0,
            area_ha                 DOUBLE PRECISION NOT NULL DEFAULT 0,
            resolution_m            INTEGER NOT NULL DEFAULT 11,

            -- Full result for faithful recall: {{trend, passes, ...}}
            detail                  JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            source                  VARCHAR(60) NOT NULL DEFAULT 'copernicus_sentinel_v1',
            note                    TEXT,

            -- Audit
            trace_id                UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_{tenant}_farm_health CHECK (health IN
                ('healthy', 'moderate', 'stressed', 'poor', 'bare', 'unknown'))
        )
        """
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_farm_checks_created '
        f'ON "{schema}".farm_checks (created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_farm_checks_lga '
        f'ON "{schema}".farm_checks (lga, created_at DESC)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_farm_checks_location '
        f'ON "{schema}".farm_checks USING GIST (location)'
    )


def _drop_farm_checks_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".farm_checks CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_farm_checks_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_farm_checks_for(tenant)
