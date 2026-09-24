"""Named settlements — the village and ward behind every alert's coordinates.

WHY
---
Asked by the operator on 2026-09-24: an alert carries its LGA and coordinates,
but a field team verifying it on the ground needs a place they can drive to —
a village, a ward. Satellites give only coordinates; the Spotlight's Mapbox
lookup knows towns but hardly any Nigerian villages, and OpenStreetMap had no
named feature within 5 km of a live Dandi alert.

GRID3 NGA Settlement Names does: 292,438 settlement points nationally, named on
foot by polio and measles vaccination teams, each tagged with its ward — 76,995
of them in our eight pilot states. Licence CC BY 4.0 (commercial use with
attribution). Kept as OUR copy rather than asked live per alert, so an alert
never goes out unnamed because a third-party service is slow or down.

Loaded by apps/ingestion/scripts/load_grid3_settlements.py (upsert on the
GRID3 global id; never deletes). About 8 MB; the GiST index makes the nearest
village for an alert a sub-millisecond lookup.

Shared reference data, so it lives in `public` — like crop_prices. A refresh
that changes a name keeps the old row version in public.deleted_records via
the retention trigger from 0051 ("no record should go").

Revision ID: 0052
Revises: 0051
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0052"
down_revision: Union[str, Sequence[str], None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.named_settlements (
            id          BIGSERIAL PRIMARY KEY,
            grid3_id    TEXT        NOT NULL UNIQUE,
            name        TEXT        NOT NULL,
            alt_name    TEXT,
            ward        TEXT,
            lga         TEXT,
            state       TEXT,
            source      TEXT,
            geom        geometry(Point, 4326) NOT NULL,
            loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_named_settlements_geom
            ON public.named_settlements USING GIST (geom)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_named_settlements_state
            ON public.named_settlements (state)
    """)
    for trigger, when in (
        ("retain_deleted_row", "AFTER DELETE ON public.named_settlements FOR EACH ROW"),
        ("retain_overwritten_row", "AFTER UPDATE ON public.named_settlements FOR EACH ROW "
                                   "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON public.named_settlements")
        op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # Dropping this table would destroy loaded reference rows; the triggers go,
    # the data stays, consistent with 0051.
    op.execute("DROP TRIGGER IF EXISTS retain_deleted_row ON public.named_settlements")
    op.execute("DROP TRIGGER IF EXISTS retain_overwritten_row ON public.named_settlements")
