"""Forecast check: the rain that was measured, and how the forecast compared.

Two tables per tenant, for every pilot. The forecast (ecmwf_forecast, 0062)
and ShockGuard's observed side are untouched; these add the comparison
between them.

rain_measured_daily
  One row per LGA per UTC day per product: the rain NASA's IMERG measured,
  averaged over the LGA by the share of its area each 0.1 deg cell covers (the
  same area weighting the forecast uses, so the two are like for like), the
  wettest single cell, and the share of the LGA's area that reached 1, 10, 25
  and 50 mm. The shares are what an ensemble chance averaged over the LGA is
  checked against. `coverage` is the share of the area with valid data.
  `product` is part of the key so a later, better product (IMERG Final) can
  sit beside the Late run without replacing it.

forecast_check_summary
  The scorecard, recomputed when new days are measured: wet-day hits, misses,
  false alarms and correct dry calls by model and by how many days ahead the
  forecast was made, the ensemble's chances against what happened, a ribbon of
  recent days and a record per LGA. Every snapshot is kept; the API reads the
  newest. The key makes a re-run on unchanged inputs a no-op.

Append-only: nothing here is ever deleted or updated (standing rule: no record
may go).

Revision ID: 0063
Revises: 0062
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0063"
down_revision: Union[str, Sequence[str], None] = "0062"
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
            CREATE TABLE IF NOT EXISTS "{schema}".rain_measured_daily (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id       VARCHAR(50)  NOT NULL,
                lga             VARCHAR(120) NOT NULL,
                day             DATE         NOT NULL,
                product         VARCHAR(40)  NOT NULL,
                rain_mm         DOUBLE PRECISION NOT NULL,
                rain_max_mm     DOUBLE PRECISION NOT NULL,
                wet_share_1mm   DOUBLE PRECISION NOT NULL,
                wet_share_10mm  DOUBLE PRECISION NOT NULL,
                wet_share_25mm  DOUBLE PRECISION NOT NULL,
                wet_share_50mm  DOUBLE PRECISION NOT NULL,
                cells           INTEGER      NOT NULL,
                coverage        DOUBLE PRECISION NOT NULL,
                source          VARCHAR(50)  NOT NULL,
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_rain_measured_lga_day
                    UNIQUE (lga, day, product)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_rain_measured_day '
            f'ON "{schema}".rain_measured_daily (day DESC)'
        )
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{schema}".forecast_check_summary (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id       VARCHAR(50)  NOT NULL,
                first_day       DATE         NOT NULL,
                last_day        DATE         NOT NULL,
                days_checked    INTEGER      NOT NULL,
                lga_days        INTEGER      NOT NULL,
                pairs           INTEGER      NOT NULL,
                summary         JSONB        NOT NULL,
                source          VARCHAR(50)  NOT NULL,
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_{tenant}_forecast_check_summary
                    UNIQUE (last_day, lga_days, pairs)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_forecast_check_recent '
            f'ON "{schema}".forecast_check_summary (created_at DESC)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP TABLE IF EXISTS "{schema}".forecast_check_summary')
        op.execute(f'DROP TABLE IF EXISTS "{schema}".rain_measured_daily')
