"""School register — every mapped school in the Nigerian pilots, from GRID3.

WHY
---
SkillsBridge counted UNICEF GIGA school locations per LGA, assigning each
school to the nearest LGA centre within ~50 km — so border LGAs were inflated
(Augie showed 329 against GRID3's 77), and the per-LGA internet, electricity
and learning-gap scores beside them were spread around national figures, not
measured (withdrawn 2026-09-26). The rebuild approved on 2026-09-26 is a
school-by-school reach list: which schools have no light at night within 2 km,
and how many people and young children live in their villages.

GRID3 NGA Schools with LGA names is the school side of that: 107,902 schools
nationally, 24,327 in our eight pilot states, each already carrying the same
LGA names our boundaries use (checked 2026-09-27: 142 of 142 match). Licence
CC BY 4.0. Pupil and teacher counts exist in the layer but are filled for only
127 pilot schools, so they are stored and not shown.

Loaded by apps/ingestion/scripts/load_grid3_schools.py (upsert on the GRID3
global id; never deletes). Shared reference data, so it lives in `public`
beside named_settlements (0052); the retention triggers from 0051 keep any
row a refresh changes ("no record should go").

Revision ID: 0057
Revises: 0056
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0057"
down_revision: Union[str, Sequence[str], None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.school_register (
            id          BIGSERIAL PRIMARY KEY,
            grid3_id    TEXT        NOT NULL UNIQUE,
            name        TEXT        NOT NULL,
            category    TEXT,
            management  TEXT,
            education   TEXT,
            ward_code   TEXT,
            lga         TEXT,
            state       TEXT,
            students    INTEGER,
            teachers    INTEGER,
            source      TEXT,
            surveyed_at DATE,
            geom        geometry(Point, 4326) NOT NULL,
            loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_school_register_geom
            ON public.school_register USING GIST (geom)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_school_register_state
            ON public.school_register (state, lga)
    """)
    for trigger, when in (
        ("retain_deleted_row", "AFTER DELETE ON public.school_register FOR EACH ROW"),
        ("retain_overwritten_row", "AFTER UPDATE ON public.school_register FOR EACH ROW "
                                   "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON public.school_register")
        op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # Loaded reference rows stay; only the triggers go, consistent with 0051.
    op.execute("DROP TRIGGER IF EXISTS retain_deleted_row ON public.school_register")
    op.execute("DROP TRIGGER IF EXISTS retain_overwritten_row ON public.school_register")
