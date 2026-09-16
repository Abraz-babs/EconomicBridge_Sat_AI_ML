"""Land-change hotspots — the shadow table for whole-LGA change detection.

WHY
---
Every per-LGA sweep so far measures one 3 x 3 km box at the LGA centroid and
pins every detection to that same point: 0.56% of the land the dashboard calls
"per-LGA". tasks/land_change_scan.py reads whole LGAs from the open Sentinel
archive and reports each change at its own position; this is where it puts them.

SHADOW BY DESIGN
----------------
Nothing reads this table. It is deliberately NOT `alert_events`, so the map,
the Farmland panel and the alert feed are untouched while the detector is
evaluated against imagery. Promoting a row into `alert_events` is a separate,
later decision.

UNIQUE (lga, season_year, kind, lon, lat)
    A re-run of the same season must not double-count one patch in what is
    meant to be evidence — the same rule as rainfall_advisory_history (0042),
    encroachment_watch_history (0045) and the storm tables (0046).

Revision ID: 0047
Revises: 0046
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0047"
down_revision: Union[str, Sequence[str], None] = "0046"
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
            CREATE TABLE IF NOT EXISTS "{schema}".land_change_hotspots (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id     VARCHAR(50)  NOT NULL,
                lga           VARCHAR(120) NOT NULL,

                -- stopped_greening = was green last season, is not now.
                -- became_bare      = stricter; now effectively non-vegetated.
                kind          VARCHAR(32)  NOT NULL,

                -- The patch's OWN position, not the LGA centroid. This column
                -- existing at all is the point of the rebuild.
                location      GEOMETRY(POINT, 4326) NOT NULL,
                lon           DOUBLE PRECISION NOT NULL,
                lat           DOUBLE PRECISION NOT NULL,
                area_ha       DOUBLE PRECISION NOT NULL,

                -- Peak rainy-season greenness either side of the change, so a
                -- reader can judge the evidence rather than trust the label.
                peak_prev     DOUBLE PRECISION,
                peak_now      DOUBLE PRECISION,

                season_year       INTEGER NOT NULL,
                prev_season_year  INTEGER NOT NULL,
                window_start      DATE NOT NULL,
                window_end        DATE NOT NULL,

                -- Share of the LGA both seasons actually saw. A low number
                -- means cloud, not calm, and the row list must be read that way.
                lga_observed_fraction DOUBLE PRECISION,

                detector_version VARCHAR(50) NOT NULL,
                detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                CONSTRAINT uq_{tenant}_land_change
                    UNIQUE (lga, season_year, kind, lon, lat)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_land_change_recent '
            f'ON "{schema}".land_change_hotspots (season_year DESC, area_ha DESC)'
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_land_change_lga '
            f'ON "{schema}".land_change_hotspots (lga, season_year DESC)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(f'DROP TABLE IF EXISTS "tenant_{tenant}".land_change_hotspots')
