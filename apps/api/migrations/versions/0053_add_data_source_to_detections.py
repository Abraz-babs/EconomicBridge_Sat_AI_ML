"""Every detection says whether it came from live satellite data or a synthetic series.

WHY
---
The operator's NASRDA demo opens ShockGuard, and two "critical flood, 0.99"
events were on it under a LIVE chip — Maiyama (Kebbi, 13 Jun 2026) and
Wushishi (Niger, 26 Jul 2026). Both were written by the on-demand scan, which
falls back to a synthetic SAR series when live data is missing and can inject
a flood for demos; with persist on, it stored the result like a detection.
CropGuard's NDVI anomaly list had the same leak.

PROVEN, not assumed (2026-09-24). The synthetic generators are deterministic
per (tenant, date), so each stored row was re-generated and re-detected:
  * shock 9af6965c… Maiyama   baseline -10.454 dB, recent -13.501, z -8.94
  * shock 846a5b63… Wushishi  baseline -11.780 dB, recent -15.806, z -10.98
      -> both reproduce EXACTLY as synthetic series + injected flood
  * ndvi  3de9eefd… FCT window 2026-08-10, baseline 0.7394
  * ndvi  75e0164d… FCT window 2026-07-27, baseline 0.7248
      -> both reproduce exactly as synthetic NDVI + injected anomaly
The other 9 NDVI anomalies match no synthetic series (their windows lag their
creation the way real Sentinel-2 does) and are left as they are.

WHAT
----
A nullable `data_source` on shock_events and ndvi_anomalies: 'live' |
'synthetic'; NULL = recorded before provenance was tracked. The four proven
rows are marked 'synthetic' — KEPT, per the standing rule that no record goes;
the read paths exclude 'synthetic' from every live view. The scan endpoints
stop storing synthetic or demo results at all.

Revision ID: 0053
Revises: 0052
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0053"
down_revision: Union[str, Sequence[str], None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)
TABLES: tuple[str, ...] = ("shock_events", "ndvi_anomalies")

# (tenant, table, id) — each proven synthetic as recorded in the docstring.
PROVEN_SYNTHETIC: tuple[tuple[str, str, str], ...] = (
    ("kebbi", "shock_events", "9af6965c-b8f4-4401-826e-af965a7a0e5b"),
    ("niger", "shock_events", "846a5b63-ee34-41ce-9440-48be4383f163"),
    ("fct", "ndvi_anomalies", "3de9eefd-d261-4638-935b-b011fa874f31"),
    ("fct", "ndvi_anomalies", "75e0164d-e36c-4754-9fbf-85c9908b8b52"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tenant in PILOT_TENANTS:
        for table in TABLES:
            qualified = f'"tenant_{tenant}".{table}'
            op.execute(f"""
                DO $body$
                BEGIN
                    IF to_regclass('{qualified}') IS NOT NULL THEN
                        ALTER TABLE {qualified} ADD COLUMN IF NOT EXISTS data_source TEXT;
                    END IF;
                END
                $body$;
            """)
    for tenant, table, row_id in PROVEN_SYNTHETIC:
        op.execute(
            f'UPDATE "tenant_{tenant}".{table} SET data_source = \'synthetic\' '
            f"WHERE id = '{row_id}' AND data_source IS NULL"
        )


def downgrade() -> None:
    # The column carries provenance a reader relies on; dropping it would put
    # the synthetic rows back on the live views. Leave it in place.
    pass
