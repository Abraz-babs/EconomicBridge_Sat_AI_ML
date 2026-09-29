"""People living near an alert — measured, not estimated.

The land detectors used to put "livelihoods at risk" on an alert as area × 4.6
and a naira value as area × ₦200,000, with the area itself taken from a
severity band. Since 2026-09-29 an alert carries one impact figure: the people
the population map (Meta & CIESIN HRSL at GRID3 villages — village_light,
migration 0054) places within 2 km of it. Stored in alert_events.people_within_2km
(migration 0060).

Use inside an INSERT under the tenant search_path, with :lon and :lat bound.
NULL when the state has no village layer yet, so "unmeasured" never reads as 0.
"""
from __future__ import annotations

RADIUS_M = 2000

PEOPLE_WITHIN_2KM_SQL = f"""(
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM village_light) THEN NULL
                ELSE COALESCE(SUM(v.people), 0) END
      FROM village_light v
     WHERE v.period = (SELECT max(period) FROM village_light)
       AND v.geom && ST_Expand(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 0.02)
       AND ST_DWithin(v.geom::geography,
                      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, {RADIUS_M})
)"""
