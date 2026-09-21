"""Per-LGA seasonal vegetation — the FARMLAND measure, one row per LGA per season.

WHY THIS EXISTS
---------------
The change detector answers "was this patch converted?" and needs a trustworthy
baseline in BOTH seasons. Where cloud hid one of them it can say nothing, and
that is why every FCT LGA reported 0% observed and read as calm. It also found
mostly roads and quarries — infrastructure, which is not what this platform is
for. The operator's standing priority is farmland and agriculture.

So this asks a one-sided agricultural question instead: how much of this LGA
reached full greenness during the rains? A SINGLE clear look showing green is
positive evidence, so cloud can only ever push the answer too LOW. Every LGA
returns a figure, Abuja included, and the figure is an honest lower bound.

WHAT THE NUMBERS MEAN, EXACTLY
------------------------------
`greened_ha`     ground that reached NDVI 0.40 at some point in the window.
                 NDVI CANNOT TELL A CROP FROM A TREE — this is an upper bound
                 on cultivated land, NOT a cropland map. Never label it
                 "cropland" in an interface or a document.
`observed_ha`    ground seen clear at least once. The only fair denominator
                 for `greened_ha`; the LGA's full area is not.
`lga_ha`         the whole LGA, so a reader can see how much was hidden.

`common_observed_ha`, `greened_ha_common`, `prev_greened_ha_common`
                 the ONLY honest way to quote a change. Each season's
                 `greened_ha` is a lower bound set by how much cloud let us
                 see, and no two seasons are hidden equally: over FCT's
                 Municipal Area Council the raw figures were 43,264 ha last
                 season against 83,395 ha this one, which reads as farmland
                 doubling and is very largely the 2025 rains being clouded
                 out. These three columns measure both seasons over the
                 footprint BOTH of them saw. Quote change from these; never
                 subtract one `greened_ha` from another.
`change_comparable`
                 and even the common footprint is not enough. It fixes "seen
                 versus not seen"; it does NOT fix "seen twice versus seen
                 eight times". A peak is a MAXIMUM OVER A SAMPLE, so the
                 season with fewer clear looks reports a lower peak for no
                 reason on the ground. FCT's Municipal Area Council ran raw
                 +93%, then +38.9% like-for-like, on a 2025 season that was
                 still barely seen. WHERE THIS IS FALSE, REPORT THE AREA AND
                 SAY THE CHANGE CANNOT BE ESTABLISHED.

Revision ID: 0049
Revises: 0048
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0049"
down_revision: Union[str, Sequence[str], None] = "0048"
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
            CREATE TABLE IF NOT EXISTS "{schema}".lga_season_vegetation (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id     VARCHAR(50)  NOT NULL,
                lga           VARCHAR(120) NOT NULL,
                season_year   INTEGER      NOT NULL,

                window_start  DATE NOT NULL,
                window_end    DATE NOT NULL,

                lga_ha        DOUBLE PRECISION NOT NULL,
                observed_ha   DOUBLE PRECISION NOT NULL,
                greened_ha    DOUBLE PRECISION NOT NULL,
                median_peak   DOUBLE PRECISION,
                n_dates       INTEGER NOT NULL,

                -- Like-for-like against the season before, over the ground
                -- both seasons actually saw. NULL for the earliest season.
                common_observed_ha     DOUBLE PRECISION,
                greened_ha_common      DOUBLE PRECISION,
                prev_greened_ha_common DOUBLE PRECISION,
                -- Clear looks the typical pixel got, and whether the two
                -- seasons were seen well enough to compare at all.
                median_looks           DOUBLE PRECISION,
                prev_median_looks      DOUBLE PRECISION,
                change_comparable      BOOLEAN NOT NULL DEFAULT FALSE,

                detector_version VARCHAR(50) NOT NULL,
                measured_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                CONSTRAINT uq_{tenant}_lga_season_veg
                    UNIQUE (lga, season_year, detector_version)
            )
            """
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_lga_season_veg '
            f'ON "{schema}".lga_season_vegetation (season_year DESC, lga)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        op.execute(f'DROP TABLE IF EXISTS "tenant_{tenant}".lga_season_vegetation')
