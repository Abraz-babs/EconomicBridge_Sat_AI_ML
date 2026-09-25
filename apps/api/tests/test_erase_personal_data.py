"""The erasure procedure — the one exception to "no record should go". DB-free."""
from __future__ import annotations

import pytest

from scripts.erase_personal_data import COUNT_ARCHIVE_SQL, KINDS, LOG_SQL, PURGE_SQL, plan

UID = "3f2b8c1e-9d4a-4c7b-8e21-5a6f0d9c1b2e"


def test_every_kind_removes_archived_copies():
    """Erasing the live row is not enough: the retention archive must lose its
    copies too, or the person's data survives in public.deleted_records."""
    assert all(k.purge_archive for k in KINDS.values())
    assert "public.deleted_records" in PURGE_SQL and "row_data->>'id' = :id" in PURGE_SQL


def test_the_log_never_holds_personal_data():
    columns = LOG_SQL.split("(", 1)[1].split(")", 1)[0].replace(" ", "").split(",")
    assert columns == ["kind", "schema_name", "table_name", "record_id", "dsr_id",
                       "rows_erased", "archive_copies_purged", "files_deleted", "note"]


def test_tenant_records_need_a_tenant():
    with pytest.raises(ValueError, match="--tenant"):
        plan("sms_subscriber", UID, None)
    kind, schema, steps = plan("sms_subscriber", UID, "kebbi")
    assert schema == "tenant_kebbi"
    assert all('"tenant_kebbi"' in s or "public.sms_outbox" in s for s in steps)


def test_sms_history_keeps_the_message_but_loses_the_number():
    _, _, steps = plan("sms_subscriber", UID, "kebbi")
    assert steps[0].startswith("UPDATE public.sms_outbox SET phone_e164 = 'ERASED'")
    assert steps[-1].startswith('DELETE FROM "tenant_kebbi"."alert_subscribers"')


def test_an_account_erasure_clears_the_audit_ip_before_deleting():
    _, schema, steps = plan("user", UID, None)
    assert schema == "public"
    assert "ip_address = NULL" in steps[0] and steps[1] == "DELETE FROM public.users WHERE id = :id"


def test_a_leaf_photo_is_deleted_from_storage_too():
    assert KINDS["crop_prediction"].file_columns == ("image_s3_bucket", "image_s3_key")


def test_an_agreement_keeps_the_contract_but_not_the_signatory():
    _, _, (step,) = plan("dpa_signatory", UID, None)
    assert step.startswith("UPDATE") and "signatory_name = NULL" in step


def test_inputs_are_validated_before_any_sql():
    with pytest.raises(ValueError, match="unknown kind"):
        plan("everything", UID, None)
    with pytest.raises(ValueError, match="UUID"):
        plan("user", "1 OR 1=1", None)
    with pytest.raises(ValueError, match="--tenant"):
        plan("farm_check", UID, "kebbi; DROP TABLE x")


def test_archive_count_and_purge_match_the_same_rows():
    assert COUNT_ARCHIVE_SQL.split("WHERE")[1] == PURGE_SQL.split("WHERE")[1]
