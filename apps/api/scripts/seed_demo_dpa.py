"""DEMO STACKS ONLY — demo org + signed DPA for every pilot (SMS demo path).

The notifications service gates subscriber-list + dispatch behind a signed
Data Processing Agreement (real PII protection). An organisation id holding a
signed DPA is therefore a credential, and this script creates one.

Creates the demo organisation if absent (idempotent) and then ensures a
signed DPA row for it across all pilot tenants.

The id comes from the DEMO_ORG_ID environment variable and is never written
into the repository. Until 2026-11-18 it was a constant in this file, and the
live farmer-SMS pipeline used that same id, so anyone reading the public repo
could call the PII-gated notify endpoints. That id has been revoked. Generate a
fresh one per demo stack (python -c "import uuid; print(uuid.uuid4())").

Run on dev/staging DEMO deployments only. NEVER on a deployment holding real
subscriber PII, and never reuse the pipeline's organisation id here.

    DEMO_ORG_ID=<fresh uuid> python -m scripts.seed_demo_dpa
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.tenants import PILOT_TENANT_IDS  # noqa: E402

def _demo_org_id() -> str:
    """The demo org id from the environment; refuse to run without a valid one."""
    raw = os.environ.get("DEMO_ORG_ID", "").strip()
    try:
        return str(UUID(raw))
    except ValueError:
        sys.exit("DEMO_ORG_ID must be set to a fresh UUID (never commit it).")


async def seed(org_id: str) -> int:
    """Ensure the demo org exists + signed DPAs for all pilots. Returns rows added."""
    factory = get_session_factory()
    added = 0
    async with factory() as session:
        # 1) The demo organisation itself (fixed UUID the frontend sends).
        # NB: permitted_tenants / bilateral_agreements are varchar[] ARRAYs in
        # the DDL (migration 0001), NOT json — cast accordingly.
        await session.execute(
            text(
                """
                INSERT INTO public.organisations
                    (id, org_id, name, type, country_iso,
                     permitted_tenants, bilateral_agreements,
                     dpa_signed, dpa_signed_at, is_active)
                SELECT CAST(:id AS uuid), 'demo-sms-org', 'EconomicBridge SMS Demo Org',
                       'ngo', 'NGA', '{}'::varchar[], '{}'::varchar[],
                       true, NOW(), true
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.organisations WHERE id = CAST(:id AS uuid)
                )
                """
            ),
            {"id": org_id},
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
                {"org": org_id, "tenant": tenant_id},
            )
            added += res.rowcount or 0
        await session.commit()
    return added


async def main() -> None:
    n = await seed(_demo_org_id())
    # The id is a credential: confirm the work, never echo the value.
    print(f"demo DPA: ensured the demo org + signed agreements for "
          f"{len(PILOT_TENANT_IDS)} pilots (added {n} new)")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
