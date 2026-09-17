"""Record what the ground did TWO seasons back, on each land-change hotspot.

WHY
---
The first measured precision run (random sample of 60, labelled against
Sentinel-2 imagery) put `became_bare` at 50% and `stopped_greening` at 7%. The
errors were not random: seven of thirteen were the same sand-bed river through
Shinkafi, whose bars shift every year, and most of the rest were fallow fields.

Both share a signature: they ALTERNATE. A road goes green to bare once and
stays bare; a sandbar revegetates and scours again, and a field rotates. So the
scan now reads a third season and records whether the ground greened in BOTH
prior years — true for 62% of confirmed conversions and only 20% of errors.

REPORTED, NOT ENFORCED
----------------------
`persistent` is stored so a reader can demand the stricter evidence. It is
deliberately NOT applied as a filter: on the labelled points it would have
halved the errors and also discarded three of eight confirmed detections,
including a Zamfara road and the Aleiro construction pad. Eighteen points is
not enough to impose that trade on every reader, and a detector that quietly
narrows what it can see is the failure this whole rebuild exists to end.

Revision ID: 0048
Revises: 0047
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0048"
down_revision: Union[str, Sequence[str], None] = "0047"
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
            f'ALTER TABLE "{schema}".land_change_hotspots '
            f"ADD COLUMN IF NOT EXISTS peak_prior DOUBLE PRECISION"
        )
        op.execute(
            f'ALTER TABLE "{schema}".land_change_hotspots '
            f"ADD COLUMN IF NOT EXISTS persistent BOOLEAN NOT NULL DEFAULT FALSE"
        )
        # The high-confidence subset a reviewer will actually ask for.
        op.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{tenant}_land_change_persistent '
            f'ON "{schema}".land_change_hotspots (season_year DESC, kind, persistent)'
        )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        op.execute(f'DROP INDEX IF EXISTS "{schema}".idx_{tenant}_land_change_persistent')
        op.execute(f'ALTER TABLE "{schema}".land_change_hotspots DROP COLUMN IF EXISTS persistent')
        op.execute(f'ALTER TABLE "{schema}".land_change_hotspots DROP COLUMN IF EXISTS peak_prior')
