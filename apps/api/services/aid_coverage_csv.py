"""CSV parsing + per-row validation for the Module 02 bulk upload endpoint.

The canonical CSV header is:

    agency_slug,lga,beneficiaries_served,last_active_at

Notes on each column:
  agency_slug          — must exist in public.aid_agencies (typo → row skipped).
  lga                  — free-text, 1..120 chars.
  beneficiaries_served — integer 0..10_000_000.
  last_active_at       — ISO-8601 date (YYYY-MM-DD), or blank.

`source` is supplied by the request (one value per upload — typically
'wfp_scope_v1', 'unhcr_progres_v1', or 'nema_manual_v1') so partner-org
imports stay distinguishable from manual_admin rows. Different sources
coexist for the same (agency, LGA) tuple — the audit trail is intact.

Why we parse + validate here instead of in the router:
  - Keeps the router under the 300-line cap (CLAUDE.md §4.3).
  - The parser doesn't know about HTTP — it's just bytes → records, which
    makes it directly unit-testable without spinning up FastAPI.
  - The router decides whether to commit, write audit_log, etc.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

from schemas.aid_coordination import BulkCoverageRowError


REQUIRED_HEADERS: frozenset[str] = frozenset(
    {"agency_slug", "lga", "beneficiaries_served"}
)
# `last_active_at` is optional in the CSV but the column header must
# still appear when supplied — we don't quietly drop typos in optional cols.
OPTIONAL_HEADERS: frozenset[str] = frozenset({"last_active_at"})

MAX_CSV_BYTES: int = 5 * 1024 * 1024     # 5 MB — typical state-level batch
MAX_ROWS: int = 5_000                    # upper bound to keep memory bounded


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One CSV row that passed shape + type validation. agency_slug
    existence is checked later, by the router (it owns the DB session)."""

    line_number: int
    agency_slug: str
    lga: str
    beneficiaries_served: int
    last_active_at: date | None


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Result of parse_csv: the valid rows + the rejected ones."""

    valid_rows: list[ParsedRow]
    errors: list[BulkCoverageRowError]
    header_line_number: int = 1


class CsvParseError(ValueError):
    """Whole-file rejection (header mismatch, oversize, encoding). Per-row
    issues live in ParseOutcome.errors, not as exceptions."""


def parse_csv(blob: bytes) -> ParseOutcome:
    """Parse bytes → ParseOutcome. Caller has the row+error counts upfront.

    Raises CsvParseError for whole-file problems: oversize, invalid UTF-8,
    header mismatch, empty file. Per-row issues (bad int, unknown date
    format, missing field) are captured in `errors` so the caller can
    return them to the operator without aborting the upload.
    """
    if not blob:
        raise CsvParseError("empty file")
    if len(blob) > MAX_CSV_BYTES:
        raise CsvParseError(
            f"file too large: {len(blob)} bytes > {MAX_CSV_BYTES}"
        )
    try:
        text = blob.decode("utf-8-sig")  # tolerate BOM from Excel exports
    except UnicodeDecodeError as exc:
        raise CsvParseError(f"invalid UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    field_set = {f.strip() for f in fieldnames}
    missing = REQUIRED_HEADERS - field_set
    if missing:
        raise CsvParseError(
            f"missing required header(s): {sorted(missing)}. "
            f"Required: {sorted(REQUIRED_HEADERS)}; "
            f"optional: {sorted(OPTIONAL_HEADERS)}."
        )
    extras = field_set - REQUIRED_HEADERS - OPTIONAL_HEADERS
    if extras:
        raise CsvParseError(
            f"unknown header(s): {sorted(extras)}. "
            f"Allowed: {sorted(REQUIRED_HEADERS | OPTIONAL_HEADERS)}."
        )

    valid: list[ParsedRow] = []
    errors: list[BulkCoverageRowError] = []
    for i, raw in enumerate(reader, start=2):  # line 1 = header, data from 2
        if i - 1 > MAX_ROWS:
            errors.append(BulkCoverageRowError(
                line_number=i, raw_row=dict(raw),
                error=f"row limit exceeded ({MAX_ROWS}); remaining rows ignored",
            ))
            break
        row_or_err = _parse_row(i, raw)
        if isinstance(row_or_err, ParsedRow):
            valid.append(row_or_err)
        else:
            errors.append(row_or_err)

    return ParseOutcome(valid_rows=valid, errors=errors)


def _parse_row(
    line_number: int, raw: dict[str, str | None],
) -> ParsedRow | BulkCoverageRowError:
    """Validate one CSV row. Returns ParsedRow on success, error on fail."""
    clean = {k: (v or "").strip() for k, v in raw.items() if k is not None}

    agency_slug = clean.get("agency_slug", "")
    lga = clean.get("lga", "")
    if not agency_slug:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error="agency_slug is required",
        )
    if not lga:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error="lga is required",
        )
    if len(agency_slug) > 40:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error="agency_slug exceeds 40 chars",
        )
    if len(lga) > 120:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error="lga exceeds 120 chars",
        )

    beneficiaries_raw = clean.get("beneficiaries_served", "0")
    try:
        beneficiaries = int(beneficiaries_raw or "0")
    except ValueError:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error=f"beneficiaries_served must be an integer (got {beneficiaries_raw!r})",
        )
    if beneficiaries < 0 or beneficiaries > 10_000_000:
        return BulkCoverageRowError(
            line_number=line_number, raw_row=clean,
            error="beneficiaries_served must be between 0 and 10_000_000",
        )

    last_active_raw = clean.get("last_active_at", "")
    last_active: date | None = None
    if last_active_raw:
        try:
            last_active = date.fromisoformat(last_active_raw)
        except ValueError:
            return BulkCoverageRowError(
                line_number=line_number, raw_row=clean,
                error=(
                    f"last_active_at must be ISO-8601 YYYY-MM-DD "
                    f"(got {last_active_raw!r})"
                ),
            )

    return ParsedRow(
        line_number=line_number,
        agency_slug=agency_slug,
        lga=lga,
        beneficiaries_served=beneficiaries,
        last_active_at=last_active,
    )
