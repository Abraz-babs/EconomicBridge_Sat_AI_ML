"""A swallowed exception must still say WHAT it was.

The IMERG region fetch logged `"... skipped: %s"` with the exception. httpx
timeout exceptions stringify to the EMPTY STRING, so a real incident produced
sixty-eight consecutive log lines reading "skipped: " with nothing after the
colon. The archive was refusing us and the logs described it as silence.

`%r` costs nothing and keeps the class name when there is no message. These
tests pin the format strings at every site that catches a BARE Exception, since
those are exactly the handlers that can receive an httpx error.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ING = pathlib.Path(__file__).resolve().parents[1]

# (file, snippet that must appear) — the log call, with %r not %s.
PINNED = [
    ("tasks/rainstorm_scan.py", 'skipped: %r"'),
    ("tasks/rainstorm_scan.py", 'rainfall scan failed for %s: %r"'),
    ("tasks/encroachment_detector.py", 'nightlight sample failed: %r"'),
    ("tasks/encroachment_detector.py", 'crop_health write skipped tenant=%s lga=%s: %r"'),
]


def test_httpx_timeouts_really_do_stringify_to_nothing():
    """The premise. If httpx ever changes this, these pins can be relaxed."""
    httpx = pytest.importorskip("httpx")

    for exc in (httpx.ReadTimeout(""), httpx.ConnectTimeout(""),
                httpx.PoolTimeout("")):
        assert str(exc) == ""
        assert type(exc).__name__ in repr(exc)


@pytest.mark.parametrize("rel,snippet", PINNED)
def test_bare_exception_handlers_log_with_repr(rel: str, snippet: str):
    assert snippet in (ING / rel).read_text(encoding="utf-8"), (
        f"{rel} must log the exception with %r — %s renders an httpx timeout "
        f"as an empty string and the failure becomes invisible"
    )


def test_no_bare_exception_handler_logs_the_exception_with_percent_s():
    """Catch new instances of the same mistake as they are written."""
    offenders: list[str] = []
    for path in (ING / "tasks").glob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not re.search(r"except\s+Exception\s+as\s+exc", line):
                continue
            # Look at the handler body for a log call carrying `exc`.
            for follow in lines[i + 1:i + 8]:
                if "log." in follow and "exc" in follow and "%s" in follow:
                    # `%s` is fine for other args; flag only when exc is the
                    # LAST substitution, i.e. the one `%s` would render empty.
                    if follow.rstrip().endswith("exc)") and '%r"' not in follow:
                        offenders.append(f"{path.name}:{i + 1 + lines[i+1:i+8].index(follow)}")
                    break
    assert not offenders, (
        "these bare-Exception handlers log the exception with %s; use %r so an "
        f"httpx timeout is not logged as an empty string: {offenders}"
    )
