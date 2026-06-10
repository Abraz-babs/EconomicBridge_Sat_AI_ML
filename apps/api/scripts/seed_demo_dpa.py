"""DEMO STACKS ONLY — demo org + signed DPA for every pilot (SMS demo path).

The notifications service gates subscriber-list + dispatch behind a signed
Data Processing Agreement (real PII protection). The dashboard's SMS demo
(Admin → SMS language preview / dispatch) sends the fixed demo-org UUID below
as ``X-Organisation-Id``, so for the demo path to work the org must exist with
EXACTLY that id and hold a signed DPA per pilot tenant.

Creates the demo organisation if absent (idempotent) and then ensures a
signed DPA row for it across all pilot tenants.

Run on dev/staging DEMO deployments only. NEVER on a production deployment
holding real subscriber PII — a signed DPA authorises PII access, and this
org's credentials are demo-grade.

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

# Must match the frontend's demo-org constant
# (SmsLanguagePreviewCard.tsx → NEXT_PUBLIC_DEMO_ORG_ID default).
DEMO_ORG_ID = "025a16c3-4c64-4115-b320-f5dbd8d8bc03"


async def seed() -> int:
    """Ensure the demo org exists + signed DPAs for all pilots. Returns rows added."""
    factory = get_session_factory()
    added = 0
    async with factory() as session:
        # 1) The demo organisation itself (fixed UUID the frontend sends).
        await session.execute(
            text(
                """
                INSERT INTO public.organisations
                    (id, org_id, name, type, country_iso,
                     permitted_tenants, bilateral_agreements,
                     dpa_signed, dpa_signed_at, is_active)
                SELECT CAST(:id AS uuid), 'demo-sms-org', 'EconomicBridge SMS Demo Org',
                       'ngo', 'NGA', CAST(:tenants AS jsonb), '[]'::jsonb,
                       true, NOW(), true
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.organisations WHERE id = CAST(:id AS uuid)
                )
                """
            ),
            {"id": DEMO_ORG_ID, "tenants": "[]"},
        )

        # 2) A signed DPA per pilot tenant (skip any already present).
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
    print(f"demo DPA: ensured demo org {DEMO_ORG_ID} + signed agreements for "
          f"{len(PILOT_TENANT_IDS)} pilots (added {n} new)")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
