"""Resend email backend — routing + payload, with httpx mocked.

Per CLAUDE.md, external services are never called for real in tests.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import get_settings  # noqa: E402
from services import email as email_svc  # noqa: E402


def _resend_settings(monkeypatch_key="re_test_key"):
    s = get_settings()
    s.email_backend = "resend"
    s.resend_api_key = monkeypatch_key
    return s


def test_invite_uses_resend_when_selected():
    with patch.object(email_svc, "get_settings", return_value=_resend_settings()):
        with patch("httpx.post") as post:
            post.return_value = MagicMock(status_code=200, text="{}")
            ok = email_svc.send_invite_email(
                to="officer@state.gov.ng", tenant_name="Kebbi State",
                activate_url="https://app/activate?token=abc",
            )
    assert ok is True
    args, kwargs = post.call_args
    payload = kwargs["json"]
    assert payload["to"] == ["officer@state.gov.ng"]
    assert "Activate" in payload["subject"]
    assert "Bearer re_test_key" in kwargs["headers"]["Authorization"]


def test_report_attaches_pdf_as_base64():
    with patch.object(email_svc, "get_settings", return_value=_resend_settings()):
        with patch("httpx.post") as post:
            post.return_value = MagicMock(status_code=201, text="{}")
            ok = email_svc.send_report_email(
                to="officer@state.gov.ng", tenant_name="Kebbi State",
                module_label="Farmland", period="June 2026",
                pdf=b"%PDF-1.4 fake", filename="report.pdf",
            )
    assert ok is True
    payload = post.call_args.kwargs["json"]
    assert payload["attachments"][0]["filename"] == "report.pdf"
    assert payload["attachments"][0]["content"]  # base64 string present


def test_no_api_key_returns_false_without_calling_http():
    s = _resend_settings(monkeypatch_key="")
    with patch.object(email_svc, "get_settings", return_value=s):
        with patch("httpx.post") as post:
            ok = email_svc.send_invite_email(
                to="x@y.com", tenant_name="T", activate_url="https://a",
            )
    assert ok is False
    post.assert_not_called()
