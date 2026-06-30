"""Send government-agency email alert digests (scheduled / one-shot).

Emails each active agency_alert_subscriptions row its NEW relevant alerts since
its last digest. Designed to run via an EventBridge -> ECS run-task on the api
task definition (same pattern as scripts.send_scheduled_reports), or by hand:

    python -m scripts.send_agency_alerts          # only sends when there's new
    python -m scripts.send_agency_alerts --force  # send even with nothing new
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.agency_alerts import send_agency_digests  # noqa: E402


async def main(*, force: bool = False) -> None:
    factory = get_session_factory()
    async with factory() as session:
        results = await send_agency_digests(session, force=force)
    sent = sum(1 for r in results if r["emailed"])
    print(f"agency-alerts: {len(results)} subscription(s), {sent} emailed")
    for r in results:
        print(f"  {r['agency']} | {r['tenant_id']}/{r['module']} | "
              f"new={r['new_alerts']} emailed={r['emailed']}")
    await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="Send a digest even when there are no new alerts.")
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
