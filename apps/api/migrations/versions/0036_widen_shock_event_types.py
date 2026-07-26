"""Widen shock_events.event_type beyond flood/drought.

ShockGuard's record is a RAINY-SEASON DISASTER REGISTER, not a flood log. The
original CHECK allowed only 'flood' and 'drought', which meant genuinely
documented events had to be either dropped or mislabelled — e.g. the Riyom and
Bassa (Plateau) rainstorms that destroyed 100+ and 20+ houses. Dropping them
hides real disasters we did capture; relabelling them 'flood' is a lie in the
data. The fix is to record them under their own type.

Types now allowed:
  flood      — inundation (SAR backscatter drop; the live detector's domain)
  drought    — sustained moisture/thermal deficit (detector's other domain)
  rainstorm  — violent rain/wind damage: roofs off, houses down, farmland
               flattened. Very common in the Nigerian rainy season and usually
               reported separately from flooding by NEMA/SEMA.
  windstorm  — damaging wind without the rain framing, as some reports word it
  landslide  — slope/gully failure, typically rain-triggered
  erosion    — gully erosion events (a distinct, chronic hazard in NG reporting)

Only flood + drought have automated detectors; the rest arrive as documented
records (source='historical_v1') or manual entry. Keeping them in the same
table means one timeline, one map, one alert path — differentiated by type
rather than flattened into it.

Applied per tenant schema (CLAUDE.md §4.2). Reversible: down() narrows back to
flood/drought, deleting rows of the new types first so the old CHECK can hold.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0036"
down_revision: Union[str, Sequence[str], None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TENANTS: tuple[str, ...] = (
    "kebbi", "benue", "plateau", "kaduna", "niger", "zamfara",
    "fct", "ghana", "senegal", "nasarawa",
)

_WIDENED = "'flood', 'drought', 'rainstorm', 'windstorm', 'landslide', 'erosion'"
_ORIGINAL = "'flood', 'drought'"


def _swap_check(tenant: str, allowed: str) -> None:
    schema = f"tenant_{tenant}"
    constraint = f"chk_{tenant}_shock_event_type"
    op.execute(
        f'ALTER TABLE "{schema}".shock_events '
        f'DROP CONSTRAINT IF EXISTS {constraint}'
    )
    op.execute(
        f'ALTER TABLE "{schema}".shock_events '
        f'ADD CONSTRAINT {constraint} CHECK (event_type IN ({allowed}))'
    )


def upgrade() -> None:
    for tenant in PILOT_TENANTS:
        _swap_check(tenant, _WIDENED)


def downgrade() -> None:
    for tenant in PILOT_TENANTS:
        schema = f"tenant_{tenant}"
        # The narrowed CHECK cannot be added while rows of the new types exist.
        op.execute(
            f'DELETE FROM "{schema}".shock_events '
            f"WHERE event_type NOT IN ({_ORIGINAL})"
        )
        _swap_check(tenant, _ORIGINAL)
