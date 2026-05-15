"""Pytest config — add the ML package root to sys.path so `from main import app` works."""
import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))
