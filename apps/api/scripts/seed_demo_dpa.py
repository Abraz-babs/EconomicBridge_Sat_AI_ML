"""DEV/DEMO ONLY — grant the demo organisation a signed DPA for every pilot.

The notifications service gates subscriber-list + dispatch behind a signed
Data Processing Agreement (real PII protection). For the dashboard SMS demo we
want the "send test alert" path to work for whichever tenant is active, so this
seeds a signed DPA row for the existing demo org across all pilot tenants.

NEVER run against production — granting a DPA authorises PII access. Idempotent:
skips any (org, tenant) that already has a signed agreement.

    python -m scripts.seed_demo_dpa
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.tenants import PILOT_TENANT_IDS  # noqa: E402

# The demo org already present in public.organisations (kebbi DPA references it).
DEMO_ORG_ID = "025a16c3-4c64-4115-b320-f5dbd8d8bc03"


async def seed() -> int:
    factory = get_session_factory()
    added = 0
    async with factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            res = await session.execute(
                text(
                    """
                    INSERT INTO public.data_processing_agreements
                        (organisation_id, tenant_id, agreement_type, status, signed_at)
                    SELECT CAST(:org AS uuid), CAST(:tenant AS varchar),
                           'dpa', 'signed', NOW()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM public.data_processing_agreements
                         WHERE organisation_id = CAST(:org AS uuid)
                           AND tenant_id = CAST(:tenant AS varchar)
                           AND status = 'signed'
                    )
                    """
                ),
                {"org": DEMO_ORG_ID, "tenant": tenant_id},
            )
            added += res.rowcount or 0
        await session.commit()
    return added


async def main() -> None:
    n = await seed()
    print(f"demo DPA: ensured signed agreements for {len(PILOT_TENANT_IDS)} pilots "
          f"under org {DEMO_ORG_ID} (added {n} new)")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
