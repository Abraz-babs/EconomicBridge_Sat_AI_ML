"""Carry out a data-protection erasure request — the ONE exception to "no record should go".

    python -m scripts.erase_personal_data --kind sms_subscriber --tenant kebbi --id <uuid>
    python -m scripts.erase_personal_data --kind user --id <uuid> --dsr <dsr uuid> --confirm

Without --confirm nothing changes: it shows what WOULD be erased (counts only,
never the personal data). With --confirm everything below runs in ONE
transaction — either all of it happens or none of it does:

  1. the kind's own steps (delete the record, or clear its personal fields,
     and the personal data that hangs off it — see KINDS);
  2. every archived copy of the record in public.deleted_records is removed —
     including the copy the retention trigger makes during step 1;
  3. a stored file (a leaf photo) is deleted from S3, after the commit;
  4. one row in public.erasure_log (0056) records what kind of record was
     erased, where and when — never the data itself.

Directors' decision, 2026-09-25: keep the archive for everything EXCEPT
personal data someone has asked to have erased (Nigeria Data Protection Act
2023). Run it on the api task (one-shot), like the other scripts.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
_TENANT = re.compile(r"^[a-z]{2,20}$")


@dataclass(frozen=True)
class Kind:
    """One kind of personal record and how it is erased."""

    table: str
    tenant_scoped: bool
    # SQL run in order with :id bound. {s} is the schema. The last statement
    # is the one that removes/clears the record itself.
    steps: tuple[str, ...]
    # Fields to read before erasing (S3 location of a stored file, if any).
    file_columns: tuple[str, str] | None = None
    purge_archive: bool = True
    note: str = ""
    count_sql: str = 'SELECT count(*) FROM {s}."{t}" WHERE id = :id'
    extra: dict = field(default_factory=dict)


KINDS: dict[str, Kind] = {
    # An account. Sign-in tokens and activity records go with it (ON DELETE
    # CASCADE); the audit trail keeps what was done but loses who and from
    # where (actor ON DELETE SET NULL, IP cleared first).
    "user": Kind(
        table="users", tenant_scoped=False,
        steps=(
            'UPDATE public.audit_log SET ip_address = NULL WHERE actor_user_id = :id',
            'DELETE FROM public.users WHERE id = :id',
        ),
        note="account deleted; tokens + activity cascade; audit actor and IP cleared",
    ),
    # A farmer / cooperative leader who receives SMS. Past messages stay as a
    # record of what was sent, with the number replaced.
    "sms_subscriber": Kind(
        table="alert_subscribers", tenant_scoped=True,
        steps=(
            "UPDATE public.sms_outbox SET phone_e164 = 'ERASED' "
            'WHERE phone_e164 = (SELECT phone_e164 FROM {s}."alert_subscribers" WHERE id = :id)',
            'DELETE FROM {s}."alert_subscribers" WHERE id = :id',
        ),
        note="subscriber deleted; their number replaced in the SMS outbox",
    ),
    # A leaf photo and its diagnosis (photo location, stored image).
    "crop_prediction": Kind(
        table="crop_predictions", tenant_scoped=True,
        steps=('DELETE FROM {s}."crop_predictions" WHERE id = :id',),
        file_columns=("image_s3_bucket", "image_s3_key"),
        note="prediction row and stored photo deleted",
    ),
    # A checked plot (its coordinates can identify a farmer's field).
    "farm_check": Kind(
        table="farm_checks", tenant_scoped=True,
        steps=('DELETE FROM {s}."farm_checks" WHERE id = :id',),
        note="farm check deleted",
    ),
    "agency_subscription": Kind(
        table="agency_alert_subscriptions", tenant_scoped=False,
        steps=("DELETE FROM public.agency_alert_subscriptions WHERE id = :id",),
        note="alert-email subscription deleted",
    ),
    "report_subscription": Kind(
        table="report_subscriptions", tenant_scoped=False,
        steps=("DELETE FROM public.report_subscriptions WHERE id = :id",),
        note="report-email subscription deleted",
    ),
    "data_subject_request": Kind(
        table="data_subject_requests", tenant_scoped=False,
        steps=("DELETE FROM public.data_subject_requests WHERE id = :id",),
        note="request deleted after it was fulfilled",
    ),
    # An agreement stays (it is the organisation's contract); the person who
    # signed it is removed from it.
    "dpa_signatory": Kind(
        table="data_processing_agreements", tenant_scoped=False,
        steps=("UPDATE public.data_processing_agreements "
               "SET signatory_name = NULL, signatory_email = NULL WHERE id = :id",),
        note="signatory name and email cleared from the agreement",
    ),
}

PURGE_SQL = (
    "DELETE FROM public.deleted_records "
    "WHERE schema_name = :schema AND table_name = :table AND row_data->>'id' = :id"
)
COUNT_ARCHIVE_SQL = (
    "SELECT count(*) FROM public.deleted_records "
    "WHERE schema_name = :schema AND table_name = :table AND row_data->>'id' = :id"
)
LOG_SQL = (
    "INSERT INTO public.erasure_log (kind, schema_name, table_name, record_id, dsr_id, "
    "rows_erased, archive_copies_purged, files_deleted, note) "
    "VALUES (:kind, :schema, :table, :id, :dsr, :rows, :purged, :files, :note)"
)


def schema_for(kind: Kind, tenant: str | None) -> str:
    if not kind.tenant_scoped:
        return "public"
    if not tenant or not _TENANT.match(tenant):
        raise ValueError("this kind of record belongs to a tenant: pass --tenant <id>")
    return f"tenant_{tenant}"


def plan(kind_name: str, record_id: str, tenant: str | None) -> tuple[Kind, str, list[str]]:
    """Validate inputs and render the statements that will run. Pure — no DB."""
    if kind_name not in KINDS:
        raise ValueError(f"unknown kind {kind_name!r}; one of {', '.join(sorted(KINDS))}")
    if not _UUID.match(record_id):
        raise ValueError("--id must be the record's UUID")
    kind = KINDS[kind_name]
    schema = schema_for(kind, tenant)
    s = f'"{schema}"' if kind.tenant_scoped else "public"
    return kind, schema, [step.format(s=s) for step in kind.steps]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Erase one person's record (NDPA request)")
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--id", required=True, help="UUID of the record")
    ap.add_argument("--tenant", help="tenant id, for tenant records")
    ap.add_argument("--dsr", help="UUID of the data-subject request being fulfilled")
    ap.add_argument("--confirm", action="store_true", help="actually erase (default: preview)")
    a = ap.parse_args(argv)

    kind, schema, steps = plan(a.kind, a.id, a.tenant)
    if a.dsr and not _UUID.match(a.dsr):
        raise SystemExit("--dsr must be a UUID")

    from sqlalchemy import create_engine, text

    from config import get_settings

    engine = create_engine(get_settings().database_url_sync, future=True)
    params = {"id": a.id, "schema": schema, "table": kind.table}
    s = f'"{schema}"' if kind.tenant_scoped else "public"
    with engine.begin() as conn:
        found = conn.execute(text(kind.count_sql.format(s=s, t=kind.table)), params).scalar()
        archived = conn.execute(text(COUNT_ARCHIVE_SQL), params).scalar()
        print(f"{a.kind} {a.id} in {schema}.{kind.table}: {found} record(s), "
              f"{archived} archived cop(ies)")
        if not found and not archived:
            print("Nothing to erase.")
            return 1
        if not a.confirm:
            print("PREVIEW ONLY — nothing changed. Steps that --confirm would run:")
            for st in steps:
                print(f"  {st}")
            print(f"  {PURGE_SQL}")
            print("  + one public.erasure_log row")
            conn.rollback()
            return 0

        file_loc = None
        if kind.file_columns:
            b, k = kind.file_columns
            file_loc = conn.execute(text(
                f'SELECT {b}, {k} FROM {s}."{kind.table}" WHERE id = :id'), params).first()
        rows = 0
        for st in steps:
            rows += conn.execute(text(st), params).rowcount or 0
        purged = conn.execute(text(PURGE_SQL), params).rowcount if kind.purge_archive else 0
        files = 0
        if file_loc and file_loc[0] and file_loc[1]:
            files = 1
        conn.execute(text(LOG_SQL), {
            **params, "kind": a.kind, "dsr": a.dsr, "rows": rows,
            "purged": purged, "files": files, "note": kind.note,
        })
    # The database change is committed; now remove the stored file. A failure
    # here is reported loudly — the row saying files_deleted=1 is then wrong
    # and the file must be removed by hand.
    if file_loc and file_loc[0] and file_loc[1]:
        import boto3
        boto3.client("s3").delete_object(Bucket=file_loc[0], Key=file_loc[1])
    print(f"ERASED: {rows} row change(s), {purged} archived cop(ies) purged, "
          f"{files} file(s) deleted — logged in public.erasure_log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
