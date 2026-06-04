"""In-process login rate limiting (brute-force mitigation).

A per-process, IP-keyed sliding window of FAILED login attempts. Not distributed
across instances — this is defence-in-depth; production should ALSO enforce a
limit at the gateway/WAF (CLAUDE.md §4.1). FastAPI runs one event loop per
worker and there's no `await` between read and write here, so a plain dict is
safe without a lock.

  too_many_failures(key) -> (blocked, retry_after_seconds)   # check before auth
  record_failure(key)                                        # on a bad attempt
  reset(key)                                                 # on success
"""
from __future__ import annotations

import time

_MAX_FAILURES = 5          # allowed failures within the window
_WINDOW_SECONDS = 300      # rolling 5-minute window

_failures: dict[str, list[float]] = {}


def _recent(key: str, now: float) -> list[float]:
    return [t for t in _failures.get(key, []) if now - t < _WINDOW_SECONDS]


def too_many_failures(key: str) -> tuple[bool, int]:
    """True (+ retry-after seconds) when ≥ MAX failures occurred in the window."""
    now = time.time()
    recent = _recent(key, now)
    _failures[key] = recent  # prune
    if len(recent) >= _MAX_FAILURES:
        return True, max(int(_WINDOW_SECONDS - (now - recent[0])) + 1, 1)
    return False, 0


def record_failure(key: str) -> None:
    now = time.time()
    _failures[key] = _recent(key, now) + [now]


def reset(key: str) -> None:
    _failures.pop(key, None)
