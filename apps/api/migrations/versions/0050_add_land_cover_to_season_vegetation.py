"""Store WHAT KIND of land greened — the farmland split that 0049 computed and threw away.

WHY THIS EXISTS AS A SEPARATE MIGRATION
---------------------------------------
Migration 0049 stores how many hectares of an LGA greened. It does not say
whether that was farmland. The scan has been deriving the answer from the Esri
/ Impact Observatory annual land-cover map since the land-cover work landed,
but the columns were never added, so every LGA's breakdown was computed and
discarded on write. This is that omission, fixed.

It matters for the headline figure. Bwari greened 89,102 ha, of which 11,307 ha
is tree canopy and 5,071 ha is built-up. Quoting the first number as farmland
overstates it by roughly 18%.

WHAT THE CLASSES MEAN, AND THE MEASURED CAVEAT
----------------------------------------------
`crops` + `rangeland`   farmland. BOTH, and reported separately, because this
                        product under-maps West African smallholder farming: it
                        calls 85.2% of Aleiro RANGELAND and only 8.4% CROPS
                        while our own measurement shows 96% of that same ground
                        greening in the rains. `crops` alone is a LOWER bound on
                        farmland, the sum an UPPER one. Never present either as
                        "cropland" on its own.
`trees` + `built`       NOT farmland, and excluded from it. This is the part the
                        land-cover map gets reliably right and the reason a new
                        road through scrub no longer reaches the farmland feed.
`bare`                  ground the map calls bare that is now greening — that is
                        cultivation EXPANDING, the opposite of the loss the
                        detector chases, and worth seeing.
`flooded_veg`           fadama. Dry-season irrigated farming, significant in
                        Kebbi; bundling it into "not farmland" would understate
                        the picture.
`land_cover_year`       the year the map describes, so a reader knows the
                        classification is a recent snapshot and not contemporary
                        with the season being measured.

Remaining classes (water, snow) are negligible here and recoverable from
`greened_ha` minus the rest.

Revision ID: 0050
Revises: 0049
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0050"
down_revision: Union[str, Sequence[str], None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)

COLUMNS: tuple[tuple[str, str], ...] = (
    ("greened_on_crops_ha", "DOUBLE PRECISION"),
    ("greened_on_rangeland_ha", "DOUBLE PRECISION"),
    ("greened_on_trees_ha", "DOUBLE PRECISION"),
    ("greened_on_built_ha", "DOUBLE PRECISION"),
    ("greened_on_bare_ha", "DOUBLE PRECISION"),
    ("greened_on_flooded_veg_ha", "DOUBLE PRECISION"),
    ("land_cover_year", "INTEGER"),
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for name, kind in COLUMNS:
            op.execute(
                f'ALTER TABLE "{schema}".lga_season_vegetation '
                f"ADD COLUMN IF NOT EXISTS {name} {kind}"
            )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for name, _kind in COLUMNS:
            op.execute(
                f'ALTER TABLE "{schema}".lga_season_vegetation '
                f"DROP COLUMN IF EXISTS {name}"
            )
