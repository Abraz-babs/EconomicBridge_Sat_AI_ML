"""Bootstrap the platform super-admin (operator) account.

Creates a 'platform' organisation and a single super_admin user from
SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD (env or root .env). Idempotent: re-runs
update the password rather than erroring. This is the only account that can
reach /admin/* — tenants get tenant_admin accounts via the onboarding invite.

    SUPER_ADMIN_EMAIL=ops@bizra.example SUPER_ADMIN_PASSWORD='…' \
        python -m scripts.seed_super_admin

NEVER commit a real password — set it in the gitignored root .env or the shell.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from config import get_settings  # noqa: E402
from core.security import hash_password  # noqa: E402
from db.engine import get_session_factory  # noqa: E402
from dependencies import ROLE_SUPER_ADMIN  # noqa: E402

_PLATFORM_ORG_SLUG = "platform"


async def seed() -> str:
    s = get_settings()
    email = s.super_admin_email.strip().lower()
    if not s.super_admin_password:
        raise SystemExit(
            "SUPER_ADMIN_PASSWORD is not set. Set it in the root .env or the "
            "environment before running this script."
        )
    pw_hash = hash_password(s.super_admin_password)

    factory = get_session_factory()
    async with factory() as session:
        org = (await session.execute(
            text(
                """
                INSERT INTO public.organisations (org_id, name, type)
                VALUES (:slug, 'EconomicBridge (Platform Operator)', 'platform')
                ON CONFLICT (org_id) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            ),
            {"slug": _PLATFORM_ORG_SLUG},
        )).first()
        org_id = org[0]

        await session.execute(
            text(
                """
                INSERT INTO public.users
                    (org_id, email, password_hash, role, full_name, is_active)
                VALUES (:org, :email, :pw, :role, 'Platform Super-Admin', true)
                ON CONFLICT (email) DO UPDATE
                  SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role,
                      org_id = EXCLUDED.org_id, is_active = true
                """
            ),
            {"org": org_id, "email": email, "pw": pw_hash, "role": ROLE_SUPER_ADMIN},
        )
        await session.commit()
    return email


if __name__ == "__main__":
    who = asyncio.run(seed())
    print(f"[ok] super-admin ready: {who}")
