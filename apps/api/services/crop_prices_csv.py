"""CSV parsing + per-row validation for the Module 04 bulk price upload.

Canonical CSV header:

    crop,region,observed_at,price_ngn_per_kg

NBS Food Price Watch publishes monthly PDF/Excel reports — the operator
transcribes the relevant cells into this canonical CSV and uploads with
`source=nbs_fpw_v1`. The same shape works for WFP HDX Nigeria food
prices (`source=wfp_hdx_v1`), FAOSTAT (`source=faostat_v1`), or any
other partner-org data source — the source tag is the audit trail.

Validation:
  crop              — 1..40 chars, lowercased before insert (NBS uses
                      mixed-case product names — we normalise).
  region            — 1..60 chars, lowercased; free-form to allow
                      both tenant slugs and aggregates (`nigeria_national`).
  observed_at       — ISO-8601 date (YYYY-MM-DD).
  price_ngn_per_kg  — float > 0, ≤ 1_000_000 (sanity bound: yam-flour
                      premiums hit ~10,000 NGN/kg; 1M is a typo backstop).

Why parsing lives here:
  - Router stays under 300 lines (CLAUDE.md §4.3).
  - Parser is pure-Python — no HTTP, no DB, directly unit-testable.
  - Same shape as services/aid_coverage_csv.py (Slice 02.live) so future
    parser changes land in one consistent place.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

from schemas.cropguard import BulkPriceRowError


REQUIRED_HEADERS: frozenset[str] = frozenset(
    {"crop", "region", "observed_at", "price_ngn_per_kg"}
)

MAX_CSV_BYTES: int = 5 * 1024 * 1024     # 5 MB — multi-year national batch
MAX_ROWS: int = 20_000                   # 14 crops × 11 regions × 130 months

# Price sanity bound. Yam-flour and processed pepper occasionally hit
# ~10_000 NGN/kg in market shocks; 1_000_000 is a typo backstop (NBS
# occasionally publishes per-100kg figures in the wrong column).
PRICE_FLOOR_NGN_PER_KG: float = 0.0
PRICE_CEIL_NGN_PER_KG: float = 1_000_000.0


@dataclass(frozen=True, slots=True)
class ParsedPriceRow:
    """One CSV row that passed shape + type validation."""

    line_number: int
    crop: str                            # lowercased
    region: str                          # lowercased
    observed_at: date
    price_ngn_per_kg: float


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    valid_rows: list[ParsedPriceRow]
    errors: list[BulkPriceRowError]


class CsvParseError(ValueError):
    """Whole-file rejection (header mismatch, oversize, encoding)."""


def parse_prices_csv(blob: bytes) -> ParseOutcome:
    """Parse bytes → ParseOutcome.

    Per-row issues land in `errors` (so a single bad row doesn't abort the
    whole batch); whole-file problems raise CsvParseError → 400 at the
    router boundary.
    """
    if not blob:
        raise CsvParseError("empty file")
    if len(blob) > MAX_CSV_BYTES:
        raise CsvParseError(
            f"file too large: {len(blob)} bytes > {MAX_CSV_BYTES}"
        )
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvParseError(f"invalid UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    field_set = {f.strip() for f in fieldnames}
    missing = REQUIRED_HEADERS - field_set
    if missing:
        raise CsvParseError(
            f"missing required header(s): {sorted(missing)}. "
            f"Required: {sorted(REQUIRED_HEADERS)}."
        )
    extras = field_set - REQUIRED_HEADERS
    if extras:
        raise CsvParseError(
            f"unknown header(s): {sorted(extras)}. "
            f"Allowed: {sorted(REQUIRED_HEADERS)}."
        )

    valid: list[ParsedPriceRow] = []
    errors: list[BulkPriceRowError] = []
    for i, raw in enumerate(reader, start=2):  # line 1 = header
        if i - 1 > MAX_ROWS:
            errors.append(BulkPriceRowError(
                line_number=i, raw_row=dict(raw),
                error=f"row limit exceeded ({MAX_ROWS}); remaining rows ignored",
            ))
            break
        row_or_err = _parse_row(i, raw)
        if isinstance(row_or_err, ParsedPriceRow):
            valid.append(row_or_err)
        else:
            errors.append(row_or_err)

    return ParseOutcome(valid_rows=valid, errors=errors)


def _parse_row(
    line_number: int, raw: dict[str, str | None],
) -> ParsedPriceRow | BulkPriceRowError:
    clean = {k: (v or "").strip() for k, v in raw.items() if k is not None}

    crop = clean.get("crop", "").lower()
    region = clean.get("region", "").lower()
    if not crop:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean, error="crop is required",
        )
    if not region:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean, error="region is required",
        )
    if len(crop) > 40:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean, error="crop exceeds 40 chars",
        )
    if len(region) > 60:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean, error="region exceeds 60 chars",
        )

    observed_raw = clean.get("observed_at", "")
    try:
        observed_at = date.fromisoformat(observed_raw)
    except ValueError:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean,
            error=(
                f"observed_at must be ISO-8601 YYYY-MM-DD "
                f"(got {observed_raw!r})"
            ),
        )

    price_raw = clean.get("price_ngn_per_kg", "")
    try:
        price = float(price_raw)
    except ValueError:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean,
            error=f"price_ngn_per_kg must be numeric (got {price_raw!r})",
        )
    if price <= PRICE_FLOOR_NGN_PER_KG:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean,
            error="price_ngn_per_kg must be > 0",
        )
    if price > PRICE_CEIL_NGN_PER_KG:
        return BulkPriceRowError(
            line_number=line_number, raw_row=clean,
            error=(
                f"price_ngn_per_kg exceeds sanity ceiling "
                f"{PRICE_CEIL_NGN_PER_KG:,.0f} — check column for per-bag/per-100kg typo"
            ),
        )

    return ParsedPriceRow(
        line_number=line_number,
        crop=crop,
        region=region,
        observed_at=observed_at,
        price_ngn_per_kg=price,
    )
