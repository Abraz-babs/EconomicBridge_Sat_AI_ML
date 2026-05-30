"""Pytest config — add the ingestion package root to sys.path.

Tests live one level deeper than the package, so we prepend the parent dir so
imports like `from main import app` resolve regardless of cwd.
"""
import sys
from pathlib import Path

import pytest

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))


@pytest.fixture(autouse=True)
def _force_mock_external_keys(monkeypatch):
    """Force external-API keys empty so tests run in deterministic mock mode
    regardless of what real values sit in the developer's .env (a live
    GIGA_API_KEY there must not push the suite onto real HTTP). Tests that
    exercise a real/configured path override the relevant key locally.
    """
    try:
        from config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "giga_api_key", "", raising=False)
        monkeypatch.setattr(settings, "itu_api_key", "", raising=False)
    except Exception:  # noqa: BLE001 — config import shouldn't break collection
        pass
