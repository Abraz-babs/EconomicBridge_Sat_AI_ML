"""create per-tenant raster_samples table (Slice 09 — Phase B)

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-26

Phase B introduces real per-pixel raster reads from cloud-optimized
GeoTIFFs (WorldPop population density, NASA Black Marble nighttime
radiance, MODIS LST, etc.). The catalog-metadata clients shipped in
Slices 01.live / 05.live tell us *which* granules cover a tenant ROI;
this table stores the *values* sampled out of those granules at named
ground-truth locations (a village, an LGA HQ, a settlement).

Schema notes
------------
* `value` and `band_name` are deliberately generic so a single table
  serves multiple raster products (WorldPop pop/km², VIIRS DNB radiance,
  MODIS LST, …). The (source, band_name) pair tells consumers what the
  value means and which physical units apply.
* `valid` distinguishes nodata pixels from real zeroes. WorldPop uses
  -99999 sentinel for unmapped areas; VIIRS uses fill values. The
  sampler writes `valid=False, value=None` for those — never silently
  treats them as 0.
* `linked_settlement_name` is nullable: it points at the originating
  ground-truth row (e.g. a poverty_villages settlement_name) when the
  sample was triggered by that row, so dashboards can JOIN cheaply.
* UNIQUE (tenant_id, location, source, band_name, observed_at) prevents
  re-running a sweep from creating duplicates. The location is stored
  via `ST_SnapToGrid` in the UNIQUE expression so floating-point noise
  doesn't defeat de-dup.

Indexes
-------
* GIST on location for bbox queries
* Composite on (tenant_id, source) for "all WorldPop samples for tenant X"
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, Sequence[str], None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def _create_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".raster_samples (
            id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                VARCHAR(50) NOT NULL,
            location                 GEOMETRY(POINT, 4326) NOT NULL,

            -- Provenance: which raster product the value came from.
            source                   VARCHAR(40) NOT NULL,
                -- 'worldpop_ppp_v1' | 'viirs_dnb_v1' | 'modis_lst_v1' | ...
            band_name                VARCHAR(40) NOT NULL,
                -- 'population_per_km2' | 'radiance_ntl' | 'lst_celsius' | ...

            -- Sampled pixel value. NULL when valid=false (nodata, off-raster,
            -- or sampler failure). Never coerce nodata to 0.
            value                    DOUBLE PRECISION,
            valid                    BOOLEAN NOT NULL DEFAULT TRUE,

            -- Calendar date the source raster represents (NOT when we sampled).
            observed_at              DATE NOT NULL,
            -- Wall-clock when the sample was taken (for audit).
            captured_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Granule traceability: e.g. 'NGA/nga_ppp_2020.tif',
            -- 'VNP46A2.A2026140.h18v07.001...'. NULL is OK for ad-hoc samples.
            granule_id               TEXT,

            -- Optional pointer back to the ground-truth row that triggered
            -- the sample (poverty_villages.settlement_name, mobility LGA,
            -- skills LGA, …). Free-text so it can identify rows across
            -- different originating tables.
            linked_settlement_name   TEXT,

            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Functional UNIQUE INDEX — PostgreSQL UNIQUE constraints can't carry
    # expressions, but UNIQUE INDEXes can. ST_SnapToGrid quantises lat/lon
    # to ~0.0001° (~11 m) so floating-point noise can't defeat de-dup.
    op.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS uq_{tenant}_raster_loc_source_band_obs '
        f'ON "{schema}".raster_samples ('
        f'  tenant_id, source, band_name, observed_at, '
        f'  ST_AsBinary(ST_SnapToGrid(location, 0.0001))'
        f')'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_raster_location '
        f'ON "{schema}".raster_samples USING GIST (location)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{tenant}_raster_source '
        f'ON "{schema}".raster_samples (tenant_id, source)'
    )


def _drop_for(tenant: str) -> None:
    schema = f"tenant_{tenant}"
    op.execute(f'DROP TABLE IF EXISTS "{schema}".raster_samples CASCADE')


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _create_for(tenant)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        _drop_for(tenant)
