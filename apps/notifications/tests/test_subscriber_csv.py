"""Unit tests for the bulk farmer-subscriber CSV parser."""
from __future__ import annotations

import pytest

from services.subscriber_csv import (
    CsvParseError,
    parse_subscriber_csv,
)


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


HEADER = "phone_e164,lga,language,severity_threshold,full_name"


def test_valid_rows_parse() -> None:
    out = parse_subscriber_csv(_csv(
        HEADER,
        "+2348030000001,Logo,ha,all,Audu",
        "+221770000003,Bakel,fr,high,Diallo",
    ))
    assert len(out.valid_rows) == 2
    assert not out.errors
    r = out.valid_rows[0]
    assert r.phone_e164 == "+2348030000001"
    assert r.lga == "Logo"
    assert r.language == "ha"
    assert r.severity_threshold == "all"


def test_defaults_when_optional_blank() -> None:
    out = parse_subscriber_csv(_csv("phone_e164,lga", "+2348030000001,Logo"))
    assert out.valid_rows[0].language == "en"
    assert out.valid_rows[0].severity_threshold == "high"
    assert out.valid_rows[0].full_name is None


def test_bad_phone_rejected_per_row() -> None:
    out = parse_subscriber_csv(_csv(HEADER, "NOTAPHONE,Logo,en,high,X"))
    assert not out.valid_rows
    assert "E.164" in out.errors[0].error


def test_bad_language_and_threshold_rejected() -> None:
    out = parse_subscriber_csv(_csv(
        HEADER,
        "+2348030000001,Logo,zz,high,X",      # bad language
        "+2348030000002,Gboko,en,whenever,X",  # bad threshold
    ))
    assert not out.valid_rows
    assert len(out.errors) == 2


def test_missing_required_header_rejects_file() -> None:
    with pytest.raises(CsvParseError):
        parse_subscriber_csv(_csv("phone_e164,language", "+2348030000001,en"))


def test_unknown_header_rejects_file() -> None:
    with pytest.raises(CsvParseError):
        parse_subscriber_csv(_csv("phone_e164,lga,wat", "+2348030000001,Logo,x"))


def test_empty_file_rejected() -> None:
    with pytest.raises(CsvParseError):
        parse_subscriber_csv(b"")
