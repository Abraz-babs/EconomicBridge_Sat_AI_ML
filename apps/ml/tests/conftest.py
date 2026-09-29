"""Pytest config — add the ML package root to sys.path so `from main import app` works."""
import os
import sys
from pathlib import Path

# The conflict and yield predictors are synthetic-data artifacts that the live
# service refuses to serve (models/provenance.py); the suite tests their
# mechanics, so it opts in before the app is imported.
os.environ.setdefault("SERVE_SYNTHETIC_MODELS", "true")

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))
