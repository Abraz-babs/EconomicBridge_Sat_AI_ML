"""Farmland alerts carry measured impact only — people within 2 km, not band estimates.

WHY
---
Two land detectors wrote impact figures onto every alert that nothing measured:

* the encroachment watch (encroachment_detector_v1) looks at one 3 km box per
  LGA, yet wrote an "affected area" picked from its severity band (critical →
  a fixed hectare figure), "livelihoods at risk" = that area × 4.6, a naira
  value = that area × ₦200,000, and a "predicted breach" ETA in hours, also
  from the band. None of the four was observed.
* the whole-LGA land-change scan (land_change_v1) measures its patch area
  from Sentinel-2 — that stays — but still multiplied it by the same two
  constants for livelihoods and naira.

The operator's rule (2026-09-29): anything fake becomes real. So:

* new column people_within_2km — the people the population map (Meta & CIESIN
  HRSL, at GRID3 villages; village_light, 0054) places within 2 km of the
  alert. Measured, and it is what the Farmland page now shows. NULL where the
  state has no village layer yet (Ghana, Senegal).
* on both detectors' rows the invented figures are cleared: livelihoods,
  naira value and ETA everywhere; the band "area" on encroachment rows. The
  land-change patch area is kept — it is measured.
* alert_events gains the overwrite archive (0051 covered deletes only), so
  every cleared value is kept in public.deleted_records — no record goes.
* mobility_indicators: cost of living, capacity and population become
  nullable (never measured per LGA; the World Bank path stops inventing
  them), with the same overwrite archive.

Revision ID: 0060
Revises: 0059
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0060"
down_revision: Union[str, Sequence[str], None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)
DETECTORS = ("encroachment_detector_v1", "land_change_v1")


def people_within_2km_sql(schema: str, point: str) -> str:
    """People at villages within 2 km of `point`; NULL when the state has no village layer."""
    return f"""(
        SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM "{schema}".village_light) THEN NULL
                    ELSE COALESCE(SUM(v.people), 0) END
          FROM "{schema}".village_light v
         WHERE v.period = (SELECT max(period) FROM "{schema}".village_light)
           AND v.geom && ST_Expand({point}, 0.02)
           AND ST_DWithin(v.geom::geography, {point}::geography, 2000)
    )"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'ALTER TABLE "{schema}".alert_events ADD COLUMN IF NOT EXISTS people_within_2km INTEGER')
        # Overwrite archive, BEFORE the correction below, so the cleared
        # figures are kept (0051's retain_old_row function).
        op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".alert_events')
        op.execute(
            f'CREATE TRIGGER retain_overwritten_row AFTER UPDATE ON "{schema}".alert_events '
            "FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION public.retain_old_row()"
        )
        # Mobility indicators: the World Bank path now writes the state-level
        # income and the national employment ratio only. Cost of living,
        # capacity and population were never measured per LGA — allow NULL,
        # and keep every overwritten row.
        for col in ("cost_of_living_index", "income_opportunity_score",
                    "displacement_capacity_index", "population"):
            op.execute(f'ALTER TABLE "{schema}".mobility_indicators ALTER COLUMN {col} DROP NOT NULL')
        op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".mobility_indicators')
        op.execute(
            f'CREATE TRIGGER retain_overwritten_row AFTER UPDATE ON "{schema}".mobility_indicators '
            "FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION public.retain_old_row()"
        )
        people = people_within_2km_sql(schema, "a.location")
        op.execute(f"""
            UPDATE "{schema}".alert_events a
               SET people_within_2km = {people},
                   livelihoods_at_risk = NULL,
                   economic_value_ngn = NULL,
                   predicted_breach_hours = NULL,
                   affected_area_ha = CASE WHEN a.model_version = 'encroachment_detector_v1'
                                           THEN NULL ELSE a.affected_area_ha END
             WHERE a.model_version IN ('encroachment_detector_v1', 'land_change_v1')
               AND a.location IS NOT NULL
        """)


def downgrade() -> None:
    # The cleared figures are in public.deleted_records; nothing is restored
    # automatically. Keep the column (a measurement); drop only the trigger.
    for tenant in PILOT_TENANTS:
        for table in ("alert_events", "mobility_indicators"):
            op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "tenant_{tenant}".{table}')
