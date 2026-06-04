"""Generate + email due scheduled reports.

Reads public.report_subscriptions, and for each ENABLED + DUE row builds the
tenant+module PDF (reusing routers.reports.render_report) and emails it
(services.email.send_report_email, SES with attachment in prod / console stub in
dev), then stamps last_sent_at.

Run on a cadence — e.g. an EventBridge rule → ECS run-task daily; each run only
sends the subscriptions that have come due, so a daily trigger is safe.

    python -m scripts.send_scheduled_reports            # send due
    python -m scripts.send_scheduled_reports --force    # ignore the due check
    python -m scripts.send_scheduled_reports --dry-run  # build but don't email/mark

Due = never sent, or last sent ≥ the cadence interval ago (monthly=30d,
quarterly=90d). The report window is the trailing interval.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from routers.reports import REPORT_SPECS, render_report  # noqa: E402
from services.email import send_report_email  # noqa: E402
from services.tenants import is_valid_tenant_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scheduled_reports")

_INTERVAL_DAYS = {"monthly": 30, "quarterly": 90}


def _is_due(last_sent_at: datetime | None, frequency: str, now: datetime) -> bool:
    if last_sent_at is None:
        return True
    return (now - last_sent_at) >= timedelta(days=_INTERVAL_DAYS.get(frequency, 30))


async def run(force: bool, dry_run: bool) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    sent = skipped = 0
    async with factory() as session:
        subs = (await session.execute(text(
            "SELECT id, tenant_id, module, frequency, recipient_email, last_sent_at "
            "FROM public.report_subscriptions WHERE enabled = TRUE"
        ))).mappings().all()

        for sub in subs:
            if not (force or _is_due(sub["last_sent_at"], sub["frequency"], now)):
                skipped += 1
                continue
            tenant, module = sub["tenant_id"], sub["module"]
            if module not in REPORT_SPECS or not is_valid_tenant_id(tenant):
                log.warning("skip %s/%s — unknown module or unprovisioned tenant", tenant, module)
                skipped += 1
                continue

            days = _INTERVAL_DAYS.get(sub["frequency"], 30)
            start, end = now - timedelta(days=days), now
            try:
                # Pin the session to the tenant schema for the report queries.
                await session.execute(text(f"SET search_path TO tenant_{tenant}, public"))
                _, pdf = await render_report(session, tenant, module, start, end)
            except Exception as exc:  # noqa: BLE001 — one bad sub must not stop the batch
                log.warning("build failed %s/%s: %s", tenant, module, exc)
                skipped += 1
                continue
            finally:
                await session.execute(text("SET search_path TO public"))

            period = f"{start.date().isoformat()} to {end.date().isoformat()}"
            fname = f"{tenant}_{module}_{start.date().isoformat()}_{end.date().isoformat()}.pdf"
            if dry_run:
                log.info("[dry-run] would email %s → %s (%d-byte PDF)",
                         f"{tenant}/{module}", sub["recipient_email"], len(pdf))
                sent += 1
                continue

            send_report_email(
                to=sub["recipient_email"], tenant_name=tenant,
                module_label=REPORT_SPECS[module].label, period=period,
                pdf=pdf, filename=fname,
            )
            await session.execute(
                text("UPDATE public.report_subscriptions SET last_sent_at = :now WHERE id = :id"),
                {"now": now, "id": sub["id"]},
            )
            await session.commit()
            log.info("sent %s/%s → %s", tenant, module, sub["recipient_email"])
            sent += 1
    return sent, skipped


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="ignore the due check")
    ap.add_argument("--dry-run", action="store_true", help="build but don't email/mark")
    args = ap.parse_args()
    sent, skipped = await run(args.force, args.dry_run)
    print(f"scheduled reports: {sent} sent, {skipped} skipped")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
