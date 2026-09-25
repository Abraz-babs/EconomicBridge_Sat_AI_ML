"""erasure_log — proof that a data-protection erasure was carried out, without the data.

WHY
---
The platform keeps every record: deleted and overwritten rows are archived to
public.deleted_records (0051, the operator's standing rule). The Nigeria Data
Protection Act 2023 also gives a person the right to have their personal data
erased. The directors decided on 2026-09-25: keep the archive for everything
EXCEPT personal data someone has asked to have erased.

scripts/erase_personal_data.py carries that out. It deletes the record, then
removes every archived copy of it in the same transaction, and writes one row
here. This row names the kind of record, where it was, and when — never the
personal data itself — so the erasure is accountable without undoing it.

The log is itself a record: retention triggers archive any change to it.

Revision ID: 0056
Revises: 0055
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0056"
down_revision: Union[str, Sequence[str], None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.erasure_log (
            id                     BIGSERIAL PRIMARY KEY,
            kind                   TEXT        NOT NULL,
            schema_name            TEXT        NOT NULL,
            table_name             TEXT        NOT NULL,
            record_id              TEXT        NOT NULL,
            dsr_id                 UUID,
            rows_erased            INTEGER     NOT NULL DEFAULT 0,
            archive_copies_purged  INTEGER     NOT NULL DEFAULT 0,
            files_deleted          INTEGER     NOT NULL DEFAULT 0,
            note                   TEXT,
            erased_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    for trigger, when in (
        ("retain_deleted_row", "AFTER DELETE ON public.erasure_log FOR EACH ROW"),
        ("retain_overwritten_row", "AFTER UPDATE ON public.erasure_log FOR EACH ROW "
                                   "WHEN (OLD.* IS DISTINCT FROM NEW.*)"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON public.erasure_log")
        op.execute(f"CREATE TRIGGER {trigger} {when} EXECUTE FUNCTION public.retain_old_row()")


def downgrade() -> None:
    # The log is a record; keep it, drop only the triggers.
    op.execute("DROP TRIGGER IF EXISTS retain_deleted_row ON public.erasure_log")
    op.execute("DROP TRIGGER IF EXISTS retain_overwritten_row ON public.erasure_log")
