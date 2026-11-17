"""ECMWF forecast per LGA, and the raw forecast cells behind the map.

Two tables per tenant, for every pilot. ShockGuard's observed side (IMERG
rainfall, storms, radar) is untouched; these hold the forecast that sits
beside it.

ecmwf_forecast
  One row per LGA per 00 UTC run. Each JSONB column is a list, one value per
  day counted from first_day (the run date):
    rain_ifs_mm, rain_ifs_max_mm, rain_aifs_mm   15 days (mm; area mean, wettest cell, AI model)
    chance_1mm .. chance_50mm                    10 days (% of the ensemble)
    temp_dawn_c, temp_afternoon_c                 6 days (deg C at 06 and 15 UTC)
  A product that was not published for a run is NULL, never filled in from
  another one.

ecmwf_forecast_cells
  One row per run: the 0.25 deg cells over the tenant, for the map layer that
  shows ECMWF's own grid instead of LGA averages. Lists are [day][row*n_cols+col],
  rows from lat0 southward, columns from lon0 eastward (cell centres).

Append-only: every run is kept (no record is ever deleted), and the UNIQUE keys
make a re-run or a manual trigger a no-op rather than a duplicate.

Revision ID: 0062
Revises: 0061
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0062"
down_revision: Union[str, Sequence[str], None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".ecmwf_forecast (
                id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id        VARCHAR(50)  NOT NULL,
                lga              VARCHAR(120) NOT NULL,
                run_at           TIMESTAMPTZ  NOT NULL,
                first_day        DATE         NOT NULL,
                cells            INTEGER      NOT NULL,
                rain_ifs_mm      JSONB        NOT NULL,
                rain_ifs_max_mm  JSONB        NOT NULL,
                rain_aifs_mm     JSONB,
                chance_1mm       JSONB,
                chance_10mm      JSONB,
                chance_25mm      JSONB,
                chance_50mm      JSONB,
                temp_dawn_c      JSONB,
                temp_afternoon_c JSONB,
                source           VARCHAR(50)  NOT NULL,
                created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_ecmwf_forecast_lga_run UNIQUE (lga, run_at)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_ecmwf_forecast_run '
            f'ON "{schema}".ecmwf_forecast (run_at DESC)'
        )
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".ecmwf_forecast_cells (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id     VARCHAR(50)  NOT NULL,
                run_at        TIMESTAMPTZ  NOT NULL,
                lat0          DOUBLE PRECISION NOT NULL,
                lon0          DOUBLE PRECISION NOT NULL,
                res           DOUBLE PRECISION NOT NULL,
                n_rows        INTEGER      NOT NULL,
                n_cols        INTEGER      NOT NULL,
                rain_ifs_mm   JSONB        NOT NULL,
                rain_aifs_mm  JSONB,
                chance_10mm   JSONB,
                source        VARCHAR(50)  NOT NULL,
                created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_ecmwf_forecast_cells_run UNIQUE (run_at)
            )
            """
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP TABLE IF EXISTS "{schema}".ecmwf_forecast_cells')
        op.execute(f'DROP TABLE IF EXISTS "{schema}".ecmwf_forecast')
