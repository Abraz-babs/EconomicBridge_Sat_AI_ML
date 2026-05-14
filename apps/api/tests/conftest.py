"""Pytest configuration — add the api package root to sys.path.

The api code is laid out as a flat package executed from `apps/api/`. Tests live
one level deeper in `apps/api/tests/`, so we prepend the parent dir to sys.path so
imports like `from main import app` resolve regardless of where pytest is invoked.
"""
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
