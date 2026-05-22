"""Tests for the Module 04 bulk price CSV upload (Slice 04.b.live).

Same shape as test_aid_coordination_bulk:
  1. Pure-Python parser tests — no HTTP, no DB. Covers shape, types,
     edge cases (BOM, line-number 1-basing, sanity ceiling).
  2. HTTP contract checks via OpenAPI inspection (DB-free per the
     Python-3.14 audit-log lesson).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from services.crop_prices_csv import (
    CsvParseError,
    MAX_CSV_BYTES,
    PRICE_CEIL_NGN_PER_KG,
    parse_prices_csv,
)


client = TestClient(app)


# ─── Parser: happy path ───────────────────────────────────────────────────


def test_parser_accepts_minimal_csv():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,2026-04-01,520\n"
        b"rice,kaduna,2026-04-01,1900.5\n"
    )
    outcome = parse_prices_csv(blob)
    assert len(outcome.valid_rows) == 2
    assert outcome.errors == []
    assert outcome.valid_rows[0].crop == "maize"
    assert outcome.valid_rows[0].region == "kebbi"
    assert outcome.valid_rows[0].observed_at == date(2026, 4, 1)
    assert outcome.valid_rows[0].price_ngn_per_kg == 520.0
    assert outcome.valid_rows[1].price_ngn_per_kg == 1900.5


def test_parser_lowercases_crop_and_region():
    """NBS bulletin headers come in mixed case — must normalise so the
    correlation query (which assumes lowercase) finds them."""
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"MAIZE,KEBBI,2026-04-01,520\n"
        b"Rice,Kaduna,2026-04-01,1900\n"
    )
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows[0].crop == "maize"
    assert outcome.valid_rows[0].region == "kebbi"
    assert outcome.valid_rows[1].crop == "rice"


def test_parser_strips_excel_bom():
    blob = "﻿crop,region,observed_at,price_ngn_per_kg\nmaize,kebbi,2026-04-01,520\n".encode(
        "utf-8"
    )
    outcome = parse_prices_csv(blob)
    assert len(outcome.valid_rows) == 1


def test_parser_line_numbers_are_1_based_with_header():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,2026-04-01,520\n"
        b"rice,kebbi,2026-04-01,1900\n"
    )
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows[0].line_number == 2
    assert outcome.valid_rows[1].line_number == 3


# ─── Parser: whole-file rejections ────────────────────────────────────────


def test_parser_rejects_empty_file():
    with pytest.raises(CsvParseError, match="empty"):
        parse_prices_csv(b"")


def test_parser_rejects_oversize_file():
    big = b"crop,region,observed_at,price_ngn_per_kg\n" + b"maize,x,2026-04-01,1\n" * 500_000
    assert len(big) > MAX_CSV_BYTES
    with pytest.raises(CsvParseError, match="too large"):
        parse_prices_csv(big)


def test_parser_rejects_missing_required_header():
    blob = b"crop,region,price_ngn_per_kg\nmaize,kebbi,520\n"   # no observed_at
    with pytest.raises(CsvParseError, match="missing required header"):
        parse_prices_csv(blob)


def test_parser_rejects_unknown_header():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg,extra_col\n"
        b"maize,kebbi,2026-04-01,520,foo\n"
    )
    with pytest.raises(CsvParseError, match="unknown header"):
        parse_prices_csv(blob)


def test_parser_rejects_invalid_utf8():
    blob = b"crop,region,observed_at,price_ngn_per_kg\n\xff\xfe,x,2026-04-01,1\n"
    with pytest.raises(CsvParseError, match="invalid UTF-8"):
        parse_prices_csv(blob)


# ─── Parser: per-row errors ──────────────────────────────────────────────


def test_parser_reports_missing_crop():
    blob = b"crop,region,observed_at,price_ngn_per_kg\n,kebbi,2026-04-01,520\n"
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows == []
    assert "crop is required" in outcome.errors[0].error
    assert outcome.errors[0].line_number == 2


def test_parser_reports_missing_region():
    blob = b"crop,region,observed_at,price_ngn_per_kg\nmaize,,2026-04-01,520\n"
    outcome = parse_prices_csv(blob)
    assert "region is required" in outcome.errors[0].error


def test_parser_reports_bad_date_format():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,01/04/2026,520\n"  # DD/MM/YYYY — not ISO
    )
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows == []
    assert "ISO-8601" in outcome.errors[0].error


def test_parser_reports_non_numeric_price():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,2026-04-01,not-a-number\n"
    )
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows == []
    assert "must be numeric" in outcome.errors[0].error


def test_parser_reports_non_positive_price():
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,2026-04-01,0\n"
        b"rice,kebbi,2026-04-01,-50\n"
    )
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows == []
    assert len(outcome.errors) == 2
    assert all("must be > 0" in e.error for e in outcome.errors)


def test_parser_reports_price_above_sanity_ceiling():
    header = b"crop,region,observed_at,price_ngn_per_kg\n"
    over = f"maize,kebbi,2026-04-01,{int(PRICE_CEIL_NGN_PER_KG) + 1}\n".encode()
    outcome = parse_prices_csv(header + over)
    assert outcome.valid_rows == []
    assert "sanity ceiling" in outcome.errors[0].error


def test_parser_reports_too_long_crop_name():
    crop = "x" * 41
    blob = f"crop,region,observed_at,price_ngn_per_kg\n{crop},kebbi,2026-04-01,520\n".encode()
    outcome = parse_prices_csv(blob)
    assert outcome.valid_rows == []
    assert "exceeds 40" in outcome.errors[0].error


def test_parser_continues_after_per_row_error():
    """One bad row does not abort the batch — good rows still pass."""
    blob = (
        b"crop,region,observed_at,price_ngn_per_kg\n"
        b"maize,kebbi,2026-04-01,520\n"          # good
        b",bad-row,2026-04-01,1\n"               # missing crop
        b"rice,kaduna,2026-04-01,1900\n"         # good
    )
    outcome = parse_prices_csv(blob)
    assert len(outcome.valid_rows) == 2
    assert len(outcome.errors) == 1
    assert outcome.errors[0].line_number == 3


# ─── HTTP contract (OpenAPI / DB-free) ────────────────────────────────────


def test_bulk_endpoint_appears_in_openapi():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/cropguard/prices/bulk" in spec["paths"]
    op = spec["paths"]["/api/v1/cropguard/prices/bulk"]["post"]
    assert op["summary"].startswith("Admin: bulk-upload")


def test_bulk_endpoint_declares_required_form_fields():
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/api/v1/cropguard/prices/bulk"]["post"]
    body_schema_ref = op["requestBody"]["content"]["multipart/form-data"]["schema"]
    if "$ref" in body_schema_ref:
        ref_name = body_schema_ref["$ref"].split("/")[-1]
        body_schema = spec["components"]["schemas"][ref_name]
    else:
        body_schema = body_schema_ref
    required = set(body_schema.get("required", []))
    assert {"file", "source"} <= required


def test_bulk_price_upload_result_carries_crops_and_regions_seen():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["BulkPriceUploadResult"]
    props = schema["properties"]
    assert {"source", "rows_received", "rows_inserted", "rows_skipped",
            "crops_seen", "regions_seen", "errors"} <= set(props.keys())


def test_bulk_price_row_error_schema_carries_raw_row():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["BulkPriceRowError"]
    props = schema["properties"]
    assert {"line_number", "raw_row", "error"} <= set(props.keys())
