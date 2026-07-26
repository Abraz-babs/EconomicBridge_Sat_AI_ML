"""Let shock_events record a detection that does not quantify impact.

Migration 0020 declared these NOT NULL DEFAULT 0:

    projected_onset_hours  INTEGER          NOT NULL DEFAULT 0
    affected_area_km2      DOUBLE PRECISION NOT NULL DEFAULT 0
    population_at_risk     INTEGER          NOT NULL DEFAULT 0

That was right for the on-demand detector, which computes all three. It is
wrong for every scan that does not: an ROI-level satellite anomaly and an
IMERG rainfall advisory both say "something is happening here" without
estimating hours-to-onset, square kilometres, or people. Both write NULL —
and an explicit NULL overrides a column DEFAULT, so both hit
NotNullViolationError.

The damage was silent and worse than it looks. `tasks/shockguard_scan.py` has
carried this since it was written, so the scheduled ShockGuard scan could
never persist a detection — the table has zero `shockguard_scan_v1` rows in
production across all ten tenants, which we had been attributing to the
Copernicus quota freeze. It would have failed the moment it found something.
`tasks/rainstorm_scan.py` hit the same wall on its first real run, on a
genuine detection: Shinkafi, Zamfara, 49.7 mm/day, p100 for that LGA.

Making the columns nullable is the correct fix rather than writing zeros:
  * the API already declares them optional (`int | None` on ShockEventRow);
  * ShockGuardPanel already branches on null, falling back to the descriptive
    zone_name — whereas zeros would render "~0 at risk over 0 km2 · onset in
    0h", which is not "unquantified", it is a false statement of no risk.

The `>= 0` CHECK constraints are unaffected: NULL satisfies a CHECK.

Reversible: down() writes 0 into existing NULLs before restoring NOT NULL,
since the old constraint cannot be re-applied while NULLs exist.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, Sequence[str], None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)

_COLUMNS: tuple[str, ...] = (
    "projected_onset_hours",
    "affected_area_km2",
    "population_at_risk",
)


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for column in _COLUMNS:
            op.execute(
                f'ALTER TABLE "{schema}".shock_events '
                f"ALTER COLUMN {column} DROP NOT NULL"
            )


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        for column in _COLUMNS:
            op.execute(
                f'UPDATE "{schema}".shock_events '
                f"SET {column} = 0 WHERE {column} IS NULL"
            )
            op.execute(
                f'ALTER TABLE "{schema}".shock_events '
                f"ALTER COLUMN {column} SET NOT NULL"
            )
