"""Seed pilot-partner ORGANISATION tenants (ECOWAS, NEMA, …).

These are *access entities*, not geographic data tenants: no schema, no map view —
they log in and view the pilot regions with the modules granted here. Registered
now with full module access but NO account; the super-admin sends each one an
activation invite (Admin → Tenant Registry → Invite) when the MoU/deal is signed.

Idempotent (UPSERT). Run after migration 0028, alongside seed_tenant_registry.

    python -m scripts.seed_partners

Add a partner by appending to PARTNERS below. `tenant_type` must be a
non-geographic category (regional_body / ng_federal / ngo / research / funder)
so no data schema is provisioned.
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
from services.modules import MODULE_KEYS  # noqa: E402
from services.tenant_categories import is_geographic  # noqa: E402

# (id, name, tenant_type, country). All get every module enabled (full-access
# pilot partners). Edit this list to add ECOWAS-equivalent partners.
PARTNERS: list[tuple[str, str, str, str]] = [
    ("ecowas", "ECOWAS Commission", "regional_body", "regional"),
    ("nema", "National Emergency Management Agency (NEMA)", "ng_federal", "nigeria"),
]


async def seed() -> tuple[int, int]:
    factory = get_session_factory()
    regs = mods = 0
    async with factory() as s:
        for tid, name, ttype, country in PARTNERS:
            if is_geographic(ttype):
                raise SystemExit(
                    f"{tid!r} has geographic category {ttype!r} — partners must be "
                    f"non-geographic (no schema). Fix PARTNERS."
                )
            await s.execute(
                text(
                    """
                    INSERT INTO public.tenant_registry
                        (id, name, tenant_type, country, status, subscription_tier)
                    VALUES (:id, :name, :ttype, :country, 'active', 'pilot')
                    ON CONFLICT (id) DO UPDATE
                      SET name = EXCLUDED.name, tenant_type = EXCLUDED.tenant_type,
                          country = EXCLUDED.country, updated_at = NOW()
                    """
                ),
                {"id": tid, "name": name, "ttype": ttype, "country": country},
            )
            regs += 1
            for mk in sorted(MODULE_KEYS):
                await s.execute(
                    text(
                        """
                        INSERT INTO public.tenant_modules (tenant_id, module_key, enabled)
                        VALUES (:t, :m, TRUE)
                        ON CONFLICT (tenant_id, module_key) DO UPDATE SET enabled = TRUE
                        """
                    ),
                    {"t": tid, "m": mk},
                )
                mods += 1
        await s.commit()
    return regs, mods


async def main() -> None:
    regs, mods = await seed()
    print(f"partners: {regs} org tenants, {mods} module rows ensured (all enabled, no account)")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
