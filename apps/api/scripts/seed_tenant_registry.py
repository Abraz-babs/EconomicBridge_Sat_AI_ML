"""Seed public.tenant_registry + public.tenant_modules for the 10 pilots.

All modules enabled by default so existing behaviour is unchanged until a
super-admin toggles something off. Idempotent (UPSERT). Run after migration
0027 (the script also creates the tables IF NOT EXISTS for convenience in dev).

    python -m scripts.seed_tenant_registry
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
from services.tenants import PILOT_TENANT_IDS  # noqa: E402

_COUNTRY = {"ghana": "ghana", "senegal": "senegal"}


def _meta(tid: str) -> tuple[str, str, str]:
    """(name, tenant_type, country) for a pilot id."""
    if tid in _COUNTRY:
        return tid.title(), "ecowas_country", _COUNTRY[tid]
    if tid == "fct":
        return "FCT (Abuja)", "ng_fct", "nigeria"
    return f"{tid.title()} State", "ng_state", "nigeria"


async def seed() -> tuple[int, int]:
    factory = get_session_factory()
    regs = mods = 0
    async with factory() as s:
        # Create tables if the migration hasn't been applied (dev convenience).
        await s.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.tenant_registry (
                id VARCHAR(50) PRIMARY KEY, name TEXT NOT NULL,
                tenant_type VARCHAR(30) NOT NULL DEFAULT 'ng_state',
                country VARCHAR(40) NOT NULL DEFAULT 'nigeria',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                mou_reference TEXT,
                subscription_tier VARCHAR(30) NOT NULL DEFAULT 'standard',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        ))
        await s.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.tenant_modules (
                tenant_id VARCHAR(50) NOT NULL, module_key VARCHAR(40) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, module_key)
            )
            """
        ))

        for tid in sorted(PILOT_TENANT_IDS):
            name, ttype, country = _meta(tid)
            await s.execute(
                text(
                    """
                    INSERT INTO public.tenant_registry (id, name, tenant_type, country, status)
                    VALUES (:id, :name, :ttype, :country, 'active')
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
                        ON CONFLICT (tenant_id, module_key) DO NOTHING
                        """
                    ),
                    {"t": tid, "m": mk},
                )
                mods += 1
        await s.commit()
    return regs, mods


async def main() -> None:
    regs, mods = await seed()
    print(f"tenant registry: {regs} tenants, {mods} module rows ensured (all enabled)")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
