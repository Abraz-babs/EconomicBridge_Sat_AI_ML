"""Mobility Compass factors — health facilities, market prices, travel time to care.

WHY
---
The compass approved on 2026-09-28 sets five measured factors side by side for
every LGA: activity (night light, 0058), this season's farming (0050's season
vegetation), the walk to a health facility, health facilities per person, and
what food and fuel cost. This migration adds the three it did not have.

public.health_facilities — the GRID3 Nigeria health facility register, one row
per facility and release. GRID3 v3.0 (updated 2026) covers 24 states, not
Benue or Plateau; v2.0 (2024, the national Health Facility Registry) covers
all 37. Both are kept: a state reads v3.0 where it exists and v2.0 otherwise,
so LGAs in one state are always compared on one release. A facility GRID3
registers without coordinates (flagged "missing xy coordinates" — 638 in
Niger, 362 in the FCT in v3.0) is kept with no geom: it counts for the state,
not for an LGA. CC BY 4.0.

public.market_prices — World Bank real-time prices (HDX "nigeria-real-time-
prices", CC BY 4.0): monthly food (per kg) and petrol (per litre) at named
markets, zone averages and the all-market average. Two sources per series:
wb_rtp_estimate_v1 (the World Bank's modelled monthly close, a continuous
series) and wb_rtp_survey_v1 (the price surveyed at the market, where one
was collected). The page plots the estimate and says when the market was
last surveyed — petrol has not been surveyed anywhere in the file since
January 2023.

tenant_<id>.village_access — modelled travel time from each GRID3 village to
the nearest health facility, walking and with motorised transport (Data for
Children Collaborative, 2024, CC BY 4.0), sampled at the village points of
the village layer (0054) with the people living there.

Two tenant views back the Reports tab with what the pages now show:
school_reach (SkillsBridge — every GRID3 school and whether any village within
2 km shows light at night, the same rule as GET /skills/reach) and
mobility_villages (Mobility Compass — every village's light trend with its
travel time to care).

Upserts only; retention triggers (0051) keep anything a refresh changes.

Revision ID: 0059
Revises: 0058
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0059"
down_revision: Union[str, Sequence[str], None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)
# Pilot tenant -> GRID3 school-register state (GRID3 spells the capital
# territory "Fct"). Keep in step with routers/skills.py GRID3_STATE.
SCHOOL_STATE = {
    "kebbi": "Kebbi", "zamfara": "Zamfara", "niger": "Niger", "kaduna": "Kaduna",
    "benue": "Benue", "plateau": "Plateau", "nasarawa": "Nasarawa", "fct": "Fct",
}
PUBLIC_TABLES = ("health_facilities", "market_prices")

# Same local-ellipsoid distance as routers/skills.py _KM (school s, village v).
_KM = """
    sqrt(power((ST_Y(v.geom) - ST_Y(s.geom)) * (111.132954
            - 0.559822 * cos(radians(2 * ST_Y(s.geom)))
            + 0.001175 * cos(radians(4 * ST_Y(s.geom)))), 2)
       + power((ST_X(v.geom) - ST_X(s.geom)) * (111.41284 * cos(radians(ST_Y(s.geom)))
            - 0.0935 * cos(radians(3 * ST_Y(s.geom)))), 2))
"""


def _retain(qualified: str) -> None:
    for trigger, when in (
        ("retain_deleted_row", f"AFTER DELETE ON {qualified} FOR EACH ROW"),
        ("retain_overwritten_row", f"AFTER UPDATE ON {qualified} FOR EACH ROW "
                                   "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {qualified}")
        op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE IF NOT EXISTS public.health_facilities (
            id          BIGSERIAL PRIMARY KEY,
            release     TEXT        NOT NULL,
            source_id   TEXT        NOT NULL,
            name        TEXT        NOT NULL,
            level       TEXT,
            type        TEXT,
            ownership   TEXT,
            functional  TEXT,
            ward        TEXT,
            lga         TEXT,
            state       TEXT        NOT NULL,
            geom        geometry(Point, 4326),
            loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (release, source_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_facilities_geom "
               "ON public.health_facilities USING GIST (geom)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_facilities_state "
               "ON public.health_facilities (state, release)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS public.market_prices (
            id          BIGSERIAL PRIMARY KEY,
            item        TEXT             NOT NULL,
            unit        TEXT             NOT NULL,
            market      TEXT             NOT NULL,
            adm1        TEXT             NOT NULL,
            adm2        TEXT,
            observed_at DATE             NOT NULL,
            price_ngn   DOUBLE PRECISION NOT NULL CHECK (price_ngn > 0),
            source      TEXT             NOT NULL,
            loaded_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
            UNIQUE (item, adm1, market, observed_at, source)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_market_prices_lookup "
               "ON public.market_prices (adm1, market, item, observed_at)")

    for table in PUBLIC_TABLES:
        _retain(f"public.{table}")

    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".village_access (
                id              BIGSERIAL PRIMARY KEY,
                settlement_id   BIGINT       NOT NULL,
                name            TEXT         NOT NULL,
                ward            TEXT,
                lga             TEXT,
                geom            geometry(Point, 4326) NOT NULL,
                people          INTEGER      NOT NULL DEFAULT 0,
                walk_min        REAL,
                drive_min       REAL,
                source          TEXT         NOT NULL,
                measured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (settlement_id, source)
            )
        """)
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_village_access_lga '
                   f'ON "{schema}".village_access (lga)')
        _retain(f'"{schema}".village_access')

        # SkillsBridge report: one row per GRID3 school in this state, with the
        # page's rule — dark = villages measured within 2 km and none lit or
        # dim; unknown = none measured. Tenants outside the register get an
        # empty view so the report answers "no rows", never an error.
        state = SCHOOL_STATE.get(tenant)
        where = f"s.state = '{state}'" if state else "FALSE"
        op.execute(f"""
            CREATE OR REPLACE VIEW "{schema}".school_reach AS
            SELECT s.loaded_at, s.name, s.category, s.management, s.lga, s.ward_code,
                   s.students, s.teachers,
                   round(ST_Y(s.geom)::numeric, 5) AS lat,
                   round(ST_X(s.geom)::numeric, 5) AS lon,
                   coalesce(ring.villages_2km, 0) AS villages_2km,
                   coalesce(ring.lit_2km, 0) AS lit_villages_2km,
                   coalesce(ring.people_2km, 0) AS people_2km,
                   CASE WHEN coalesce(ring.lit_2km, 0) + coalesce(ring.unlit_2km, 0) = 0
                        THEN 'unknown'
                        WHEN ring.lit_2km > 0 THEN 'lit' ELSE 'dark' END AS light,
                   CASE WHEN coalesce(ring.lit_2km, 0) = 0 AND coalesce(ring.unlit_2km, 0) > 0
                        THEN 1 ELSE 0 END AS no_light_2km
              FROM public.school_register s
              LEFT JOIN LATERAL (
                  SELECT count(*) AS villages_2km,
                         count(*) FILTER (WHERE c.light_class IN ('lit', 'dim')) AS lit_2km,
                         count(*) FILTER (WHERE c.light_class = 'unlit') AS unlit_2km,
                         sum(c.people) AS people_2km
                    FROM (SELECT v.light_class, v.people, {_KM} AS km
                            FROM "{schema}".village_light v
                           WHERE v.period = (SELECT max(period) FROM "{schema}".village_light)
                             AND v.geom && ST_Expand(s.geom, 0.02)) c
                   WHERE c.km <= 2.0
              ) ring ON TRUE
             WHERE {where}
        """)

        # Mobility Compass report: every village's light trend (latest run)
        # beside its modelled travel time to the nearest health facility.
        op.execute(f"""
            CREATE OR REPLACE VIEW "{schema}".mobility_villages AS
            SELECT t.measured_at, t.name, t.ward, t.lga, t.people,
                   t.status AS light_status, t.since_year,
                   round(a.walk_min::numeric, 0) AS walk_min,
                   round(a.drive_min::numeric, 0) AS drive_min,
                   CASE WHEN t.status = 'gone_dark' THEN 1 ELSE 0 END AS gone_dark,
                   CASE WHEN t.status = 'newly_lit' THEN 1 ELSE 0 END AS newly_lit,
                   CASE WHEN a.walk_min > 60 THEN t.people ELSE 0 END AS people_over_hour_walk,
                   round(ST_Y(t.geom)::numeric, 5) AS lat,
                   round(ST_X(t.geom)::numeric, 5) AS lon
              FROM "{schema}".village_light_trend t
              LEFT JOIN "{schema}".village_access a ON a.settlement_id = t.settlement_id
             WHERE t.last_year = (SELECT max(last_year) FROM "{schema}".village_light_trend)
        """)


def downgrade() -> None:
    # Measurements are records: keep the tables, drop the views and triggers.
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP VIEW IF EXISTS "{schema}".mobility_villages')
        op.execute(f'DROP VIEW IF EXISTS "{schema}".school_reach')
        op.execute(f'DROP TRIGGER IF EXISTS retain_deleted_row ON "{schema}".village_access')
        op.execute(f'DROP TRIGGER IF EXISTS retain_overwritten_row ON "{schema}".village_access')
    for table in PUBLIC_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS retain_deleted_row ON public.{table}")
        op.execute(f"DROP TRIGGER IF EXISTS retain_overwritten_row ON public.{table}")
