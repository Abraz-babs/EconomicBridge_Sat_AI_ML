"""Migration 0051 retains every deleted record — keep it that way.

The operator's standing rule (2026-09-24): no record may go. These tests pin
the two ways that rule could quietly break: a new DELETE added on a table the
archive does not cover, and a downgrade that drops the archive itself.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

APPS = Path(__file__).resolve().parents[2]
MIGRATION = APPS / "api" / "migrations" / "versions" / "0051_retain_every_deleted_record.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0051", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_table_a_job_deletes_from_is_archived():
    """Scan the scheduled jobs for DELETE FROM and require each target table to
    carry the archive trigger. A new delete path on an unarchived table fails
    here, in CI, instead of silently destroying records in production."""
    m = _migration()
    covered = set(m.TENANT_TABLES) | set(m.PUBLIC_TABLES)
    targets = set()
    for src in (APPS / "ingestion" / "tasks").glob("*.py"):
        for table in re.findall(r"DELETE FROM\s+(?:public\.)?([a-z_]+)", src.read_text("utf-8")):
            targets.add(table)
    assert targets, "the scan found no DELETE statements — the regex has gone stale"
    missing = sorted(targets - covered)
    assert not missing, f"deleted from but not archived by 0051: {missing}"


def test_downgrade_never_drops_the_archive():
    src = MIGRATION.read_text("utf-8")
    downgrade = src[src.index("def downgrade"):]
    assert "DROP TABLE" not in downgrade.upper()


def test_the_trigger_copies_the_whole_row_as_jsonb():
    """JSONB, not a column-for-column copy: a later ALTER TABLE on a source
    table must never be able to make the trigger — and so the delete, and so
    the pipeline — fail."""
    src = MIGRATION.read_text("utf-8")
    assert "to_jsonb(OLD)" in src
    assert "AFTER DELETE" in src


def test_overwritten_season_measures_are_kept_too():
    m = _migration()
    assert "lga_season_vegetation" in m.UPDATE_TABLES
    assert "OLD.* IS DISTINCT FROM NEW.*" in MIGRATION.read_text("utf-8")
