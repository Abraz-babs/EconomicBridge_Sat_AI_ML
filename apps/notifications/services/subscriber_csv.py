"""CSV parsing + per-row validation for the bulk farmer-subscriber import.

Canonical CSV header:

    phone_e164,lga,language,severity_threshold

  phone_e164          — E.164, +<country><number> (required).
  lga                 — LGA / area name, 1..120 chars (required).
  language            — en|fr|pt|ha|yo|ig (optional, default en).
  severity_threshold  — critical|high|medium|all (optional, default high).
  full_name           — optional, ≤255 chars.

Partner agencies (state ag dept, NEMA, cooperatives) supply these lists per
state under a data-sharing agreement — farmers don't self-register. The parser
is HTTP-ignorant (bytes → records) so it's unit-testable on its own; the router
owns the DB upsert + transaction.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from schemas.notify import BulkSubscriberRowError


REQUIRED_HEADERS: frozenset[str] = frozenset({"phone_e164", "lga"})
OPTIONAL_HEADERS: frozenset[str] = frozenset(
    {"language", "severity_threshold", "full_name"}
)

VALID_LANGUAGES: frozenset[str] = frozenset({"en", "fr", "pt", "ha", "yo", "ig"})
VALID_THRESHOLDS: frozenset[str] = frozenset({"critical", "high", "medium", "all"})

PHONE_RE = re.compile(r"^\+[1-9][0-9]{6,15}$")

MAX_CSV_BYTES: int = 5 * 1024 * 1024   # 5 MB
MAX_ROWS: int = 50_000                 # state-level farmer rosters can be large


@dataclass(frozen=True, slots=True)
class ParsedSubscriber:
    line_number: int
    phone_e164: str
    lga: str
    language: str
    severity_threshold: str
    full_name: str | None


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    valid_rows: list[ParsedSubscriber]
    errors: list[BulkSubscriberRowError]


class CsvParseError(ValueError):
    """Whole-file rejection (header mismatch, oversize, encoding)."""


def parse_subscriber_csv(blob: bytes) -> ParseOutcome:
    if not blob:
        raise CsvParseError("empty file")
    if len(blob) > MAX_CSV_BYTES:
        raise CsvParseError(f"file too large: {len(blob)} bytes > {MAX_CSV_BYTES}")
    try:
        text = blob.decode("utf-8-sig")  # tolerate Excel BOM
    except UnicodeDecodeError as exc:
        raise CsvParseError(f"invalid UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    field_set = {f.strip() for f in (reader.fieldnames or [])}
    missing = REQUIRED_HEADERS - field_set
    if missing:
        raise CsvParseError(
            f"missing required header(s): {sorted(missing)}. "
            f"Required: {sorted(REQUIRED_HEADERS)}; optional: {sorted(OPTIONAL_HEADERS)}."
        )
    extras = field_set - REQUIRED_HEADERS - OPTIONAL_HEADERS
    if extras:
        raise CsvParseError(
            f"unknown header(s): {sorted(extras)}. "
            f"Allowed: {sorted(REQUIRED_HEADERS | OPTIONAL_HEADERS)}."
        )

    valid: list[ParsedSubscriber] = []
    errors: list[BulkSubscriberRowError] = []
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            errors.append(BulkSubscriberRowError(
                line_number=i, raw_row={k: (v or "") for k, v in raw.items() if k},
                error=f"row limit exceeded ({MAX_ROWS}); remaining rows ignored",
            ))
            break
        row_or_err = _parse_row(i, raw)
        (valid if isinstance(row_or_err, ParsedSubscriber) else errors).append(
            row_or_err  # type: ignore[arg-type]
        )
    return ParseOutcome(valid_rows=valid, errors=errors)


def _parse_row(
    line_number: int, raw: dict[str, str | None],
) -> ParsedSubscriber | BulkSubscriberRowError:
    clean = {k: (v or "").strip() for k, v in raw.items() if k is not None}

    def err(msg: str) -> BulkSubscriberRowError:
        return BulkSubscriberRowError(line_number=line_number, raw_row=clean, error=msg)

    phone = clean.get("phone_e164", "")
    lga = clean.get("lga", "")
    if not phone:
        return err("phone_e164 is required")
    if not PHONE_RE.match(phone):
        return err(f"phone_e164 must be E.164 like +2348012345678 (got {phone!r})")
    if not lga:
        return err("lga is required")
    if len(lga) > 120:
        return err("lga exceeds 120 chars")

    language = (clean.get("language") or "en").lower()
    if language not in VALID_LANGUAGES:
        return err(f"language must be one of {sorted(VALID_LANGUAGES)} (got {language!r})")

    threshold = (clean.get("severity_threshold") or "high").lower()
    if threshold not in VALID_THRESHOLDS:
        return err(
            f"severity_threshold must be one of {sorted(VALID_THRESHOLDS)} "
            f"(got {threshold!r})"
        )

    full_name = clean.get("full_name") or None
    if full_name and len(full_name) > 255:
        return err("full_name exceeds 255 chars")

    return ParsedSubscriber(
        line_number=line_number,
        phone_e164=phone,
        lga=lga,
        language=language,
        severity_threshold=threshold,
        full_name=full_name,
    )
