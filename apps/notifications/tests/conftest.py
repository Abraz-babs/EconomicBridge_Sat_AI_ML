"""Pytest config — make `from main import app` resolve regardless of cwd."""
import sys
from pathlib import Path

NOTIF_ROOT = Path(__file__).resolve().parent.parent
if str(NOTIF_ROOT) not in sys.path:
    sys.path.insert(0, str(NOTIF_ROOT))
