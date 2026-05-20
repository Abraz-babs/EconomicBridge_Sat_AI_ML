"""align tenant_nasarawa.heat_signatures with the canonical 0004 shape

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-20

Migration 0008 created tenant_nasarawa.heat_signatures from a leaner
template than migration 0004 used for the original 9 pilots. Four column
names drifted:

  | 0008 (nasarawa) | 0004 (canonical) |
  |-----------------|------------------|
  | acquisition_time| detected_at      |
  | brightness_kelvin| brightness_k    |
  | frp_mw          | frp              |
  | day_night       | daynight         |

The conflict-prediction pipeline (apps/ingestion/tasks/conflict_pipeline.py)
queries `brightness_k` + `detected_at` from every tenant. Nasarawa failed
with "column brightness_k does not exist" the first time it ran in
production.

This migration renames the four columns in place and adds the three
that were never created in 0008 (`bright_t31_k`, `scan`, `track`). All
operations are idempotent (`IF EXISTS` / `IF NOT EXISTS`) so a re-run
on a partially-migrated database is safe.

The two seed `heat_signatures` rows (if any) survive the rename — Postgres
ALTER ... RENAME COLUMN keeps the data, just changes the metadata.

Sibling fix in spirit to migration 0009 (which aligned tenant_nasarawa
.alert_events). Together they close out the 0008 drift.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "tenant_nasarawa"
TABLE = f'"{SCHEMA}".heat_signatures'


def _rename_if_exists(old: str, new: str) -> None:
    """Rename `old` to `new` only if `old` currently exists. Idempotent."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = '{SCHEMA}'
                   AND table_name = 'heat_signatures'
                   AND column_name = '{old}'
            ) THEN
                ALTER TABLE {TABLE} RENAME COLUMN {old} TO {new};
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    # Column renames — bring the four drifted names into line.
    _rename_if_exists("acquisition_time", "detected_at")
    _rename_if_exists("brightness_kelvin", "brightness_k")
    _rename_if_exists("frp_mw", "frp")
    _rename_if_exists("day_night", "daynight")

    # Missing columns from 0008. Canonical types per migration 0004.
    for ddl in (
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS bright_t31_k DOUBLE PRECISION",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS scan         DOUBLE PRECISION",
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS track        DOUBLE PRECISION",
    ):
        op.execute(ddl)

    # Confidence width — 0008 made it SMALLINT with a CHECK (0..100), 0004
    # uses VARCHAR(20) so it can store VIIRS's text tokens ('h'/'n'/'l').
    # We drop the integer CHECK first (it would block the type change),
    # then convert the column, then leave the constraint off (no
    # equivalent canonical CHECK in 0004 — confidence is a free string).
    op.execute(
        f"""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT data_type INTO current_type
              FROM information_schema.columns
             WHERE table_schema = '{SCHEMA}'
               AND table_name = 'heat_signatures'
               AND column_name = 'confidence';
            IF current_type = 'smallint' THEN
                ALTER TABLE {TABLE}
                    DROP CONSTRAINT IF EXISTS chk_nasarawa_heat_confidence;
                ALTER TABLE {TABLE}
                    ALTER COLUMN confidence TYPE VARCHAR(20)
                    USING confidence::text;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    # No real downgrade — we cannot lossily revert VARCHAR -> SMALLINT for
    # confidence (would corrupt 'h'/'n' values). Renames are also one-way
    # in our deployment process. Migration 0008 was the bug; rolling back
    # to its shape is not a desired state.
    raise NotImplementedError("Migration 0012 is forward-only.")
