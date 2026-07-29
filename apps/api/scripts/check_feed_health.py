"""Run the feed-health watchdog and email the operator when something is wrong.

    python -m scripts.check_feed_health              # check, email if unhealthy
    python -m scripts.check_feed_health --always     # email even when healthy
    python -m scripts.check_feed_health --dry-run    # print, never email or mark

Designed to run daily on the api task via EventBridge Scheduler, the same way
scripts.send_scheduled_reports does — the api task is the one holding
RESEND_API_KEY, which is why the watchdog lives here rather than beside the
scheduler in the ingestion service.

SILENCE MEANS HEALTHY. It emails only on findings, so a message in the inbox
always means something needs a look. Exit code is 1 on findings so a scheduler
or CI caller can treat it as a failure too.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import get_settings  # noqa: E402
from db.engine import get_session_factory  # noqa: E402
from services.email import send_alert_email  # noqa: E402
from services.feed_health import format_email, run_health_check  # noqa: E402
from services.tenants import PILOT_TENANT_IDS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("feed_health")


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Feed-health watchdog")
    ap.add_argument("--always", action="store_true",
                    help="email even when everything is healthy")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report; do not email or record marks")
    args = ap.parse_args(argv)

    factory = get_session_factory()
    async with factory() as session:
        report = await run_health_check(session, sorted(PILOT_TENANT_IDS))
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    log.info("feed health: %s", report.summary())
    for obs in report.observations:
        log.info("  ok  %s", obs)
    for f in report.findings:
        log.error("  %-8s %s — %s", f.severity.upper(), f.subject, f.detail)

    if args.dry_run:
        subject, body = format_email(report)
        print("\n--- would send ---\n" + subject + "\n\n" + body)
        return 1 if report.findings else 0

    if report.findings or args.always:
        to = get_settings().super_admin_email
        subject, body = format_email(report)
        sent = send_alert_email(to=to, subject=subject, body=body)
        log.info("watchdog email to %s: %s", to,
                 "sent" if sent else "NOT sent (console backend or send failed)")

    return 1 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
