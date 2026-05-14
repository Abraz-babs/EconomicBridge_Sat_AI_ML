"""Pytest config — add the ingestion package root to sys.path.

Tests live one level deeper than the package, so we prepend the parent dir so
imports like `from main import app` resolve regardless of cwd.
"""
import sys
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parent.parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))
