"""Tests for the Module 02 bulk CSV upload (Slice 02.live).

Two layers:
  1. Pure-Python parser tests against services/aid_coverage_csv.py — no
     HTTP, no DB. Covers shape, type, edge cases.
  2. HTTP contract tests against POST /aid_coordination/coverage/bulk —
     DB-free where possible (static OpenAPI checks per the Python-3.14
     audit-log lesson); the few that need a session use TestClient.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from services.aid_coverage_csv import (
    CsvParseError,
    MAX_CSV_BYTES,
    parse_csv,
)


client = TestClient(app)


# ─── Parser: happy path ───────────────────────────────────────────────────


def test_parser_accepts_minimal_csv():
    blob = (
        b"agency_slug,lga,beneficiaries_served\n"
        b"wfp,Argungu,12500\n"
        b"unhcr,Birnin Kebbi,3400\n"
    )
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 2
    assert outcome.errors == []
    r0 = outcome.valid_rows[0]
    assert r0.agency_slug == "wfp"
    assert r0.lga == "Argungu"
    assert r0.beneficiaries_served == 12500
    assert r0.last_active_at is None


def test_parser_accepts_all_columns():
    blob = (
        b"agency_slug,lga,beneficiaries_served,last_active_at\n"
        b"wfp,Argungu,12500,2026-04-15\n"
    )
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 1
    assert outcome.valid_rows[0].last_active_at == date(2026, 4, 15)


def test_parser_strips_excel_bom():
    """Excel's CSV export prepends \\ufeff — must not break header detection."""
    blob = "﻿agency_slug,lga,beneficiaries_served\nwfp,Argungu,1\n".encode("utf-8")
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 1


def test_parser_line_numbers_are_1_based_with_header():
    blob = b"agency_slug,lga,beneficiaries_served\nwfp,Argungu,1\nunhcr,Bunza,2\n"
    outcome = parse_csv(blob)
    # Line 1 = header, data rows start at line 2.
    assert outcome.valid_rows[0].line_number == 2
    assert outcome.valid_rows[1].line_number == 3


# ─── Parser: whole-file rejections ────────────────────────────────────────


def test_parser_rejects_empty_file():
    with pytest.raises(CsvParseError, match="empty"):
        parse_csv(b"")


def test_parser_rejects_oversize_file():
    """File > MAX_CSV_BYTES (5 MB) aborts before per-row work."""
    big = b"agency_slug,lga,beneficiaries_served\n" + b"wfp,X,1\n" * 1_000_000
    assert len(big) > MAX_CSV_BYTES
    with pytest.raises(CsvParseError, match="too large"):
        parse_csv(big)


def test_parser_rejects_missing_required_header():
    blob = b"agency_slug,beneficiaries_served\nwfp,1\n"   # no lga
    with pytest.raises(CsvParseError, match="missing required header"):
        parse_csv(blob)


def test_parser_rejects_unknown_header():
    blob = b"agency_slug,lga,beneficiaries_served,extra_col\nwfp,Argungu,1,foo\n"
    with pytest.raises(CsvParseError, match="unknown header"):
        parse_csv(blob)


def test_parser_rejects_invalid_utf8():
    blob = b"agency_slug,lga,beneficiaries_served\n\xff\xfe,X,1\n"
    with pytest.raises(CsvParseError, match="invalid UTF-8"):
        parse_csv(blob)


# ─── Parser: per-row errors (NOT whole-file rejections) ──────────────────


def test_parser_reports_missing_agency_slug_per_row():
    blob = b"agency_slug,lga,beneficiaries_served\n,Argungu,1\nwfp,Birnin Kebbi,2\n"
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 1
    assert len(outcome.errors) == 1
    assert outcome.errors[0].line_number == 2
    assert "agency_slug is required" in outcome.errors[0].error


def test_parser_reports_missing_lga_per_row():
    blob = b"agency_slug,lga,beneficiaries_served\nwfp,,1\n"
    outcome = parse_csv(blob)
    assert outcome.valid_rows == []
    assert len(outcome.errors) == 1
    assert "lga is required" in outcome.errors[0].error


def test_parser_reports_non_integer_beneficiaries():
    blob = b"agency_slug,lga,beneficiaries_served\nwfp,Argungu,not-a-number\n"
    outcome = parse_csv(blob)
    assert outcome.valid_rows == []
    assert len(outcome.errors) == 1
    assert "must be an integer" in outcome.errors[0].error


def test_parser_reports_out_of_range_beneficiaries():
    blob = b"agency_slug,lga,beneficiaries_served\nwfp,Argungu,-5\n"
    outcome = parse_csv(blob)
    assert outcome.valid_rows == []
    assert "between 0 and 10_000_000" in outcome.errors[0].error


def test_parser_reports_bad_date_format():
    blob = (
        b"agency_slug,lga,beneficiaries_served,last_active_at\n"
        b"wfp,Argungu,1,15/04/2026\n"    # not ISO-8601
    )
    outcome = parse_csv(blob)
    assert outcome.valid_rows == []
    assert "ISO-8601" in outcome.errors[0].error


def test_parser_accepts_blank_optional_date():
    blob = (
        b"agency_slug,lga,beneficiaries_served,last_active_at\n"
        b"wfp,Argungu,1,\n"
    )
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 1
    assert outcome.valid_rows[0].last_active_at is None


def test_parser_reports_too_long_agency_slug():
    long_slug = "x" * 41
    blob = f"agency_slug,lga,beneficiaries_served\n{long_slug},Argungu,1\n".encode()
    outcome = parse_csv(blob)
    assert outcome.valid_rows == []
    assert "exceeds 40" in outcome.errors[0].error


def test_parser_continues_after_per_row_error():
    """One bad row does not abort the batch — good rows still pass."""
    blob = (
        b"agency_slug,lga,beneficiaries_served\n"
        b"wfp,Argungu,12500\n"
        b",bad-row-no-slug,1\n"
        b"unhcr,Birnin Kebbi,3400\n"
    )
    outcome = parse_csv(blob)
    assert len(outcome.valid_rows) == 2
    assert len(outcome.errors) == 1
    assert outcome.errors[0].line_number == 3


# ─── HTTP contract: tenant header + form schema ───────────────────────────


def test_bulk_endpoint_without_tenant_header_returns_400():
    csv_bytes = b"agency_slug,lga,beneficiaries_served\nwfp,Argungu,1\n"
    r = client.post(
        "/api/v1/aid_coordination/coverage/bulk",
        files={"file": ("c.csv", csv_bytes, "text/csv")},
        data={"source": "wfp_scope_v1"},
    )
    assert r.status_code == 400
    assert "X-Tenant-Id" in r.text


def test_bulk_endpoint_unknown_tenant_returns_404():
    csv_bytes = b"agency_slug,lga,beneficiaries_served\nwfp,Argungu,1\n"
    r = client.post(
        "/api/v1/aid_coordination/coverage/bulk",
        headers={"X-Tenant-Id": "atlantis"},
        files={"file": ("c.csv", csv_bytes, "text/csv")},
        data={"source": "wfp_scope_v1"},
    )
    assert r.status_code == 404


# ─── HTTP contract: OpenAPI shape (DB-free per Python-3.14 lesson) ────────


def test_bulk_endpoint_appears_in_openapi():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/aid_coordination/coverage/bulk" in spec["paths"]
    op = spec["paths"]["/api/v1/aid_coordination/coverage/bulk"]["post"]
    assert op["summary"].startswith("Admin: bulk-upload")


def test_bulk_endpoint_declares_file_and_source_as_required_form_fields():
    """Static OpenAPI check — both fields must be required so the admin UI
    surfaces a clean error rather than silently uploading without a tag."""
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/api/v1/aid_coordination/coverage/bulk"]["post"]
    body_schema_ref = op["requestBody"]["content"]["multipart/form-data"]["schema"]
    if "$ref" in body_schema_ref:
        ref_name = body_schema_ref["$ref"].split("/")[-1]
        body_schema = spec["components"]["schemas"][ref_name]
    else:
        body_schema = body_schema_ref
    required = set(body_schema.get("required", []))
    assert {"file", "source"} <= required


def test_bulk_endpoint_response_schema_is_BulkCoverageUploadResult():
    """The response envelope must wrap the BulkCoverageUploadResult schema
    so the admin UI can rely on rows_inserted / rows_skipped / errors."""
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["BulkCoverageUploadResult"]
    props = schema["properties"]
    assert {"tenant_id", "source", "rows_received", "rows_inserted",
            "rows_skipped", "errors"} <= set(props.keys())


def test_bulk_row_error_schema_carries_raw_row_for_diagnostics():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["BulkCoverageRowError"]
    props = schema["properties"]
    assert "line_number" in props
    assert "raw_row" in props
    assert "error" in props
