"""Tenant onboarding — provision the login account behind a registered tenant.

When a super-admin registers a tenant we also create:
  * an `organisations` row (org_id = tenant slug, permitted_tenants scoped to it)
  * a `users` row: role=tenant_admin, is_active=false, empty password_hash —
    a *pending* account that can't log in until activated.

We then mint a single-use invite token. The caller (admin router) builds the
activation URL, emails it, and — in dev — echoes it back so it can be tested.

Idempotent: re-registering a tenant upserts the org and reuses the pending user.
An already-activated user is left untouched and gets no new invite (re-issuing
is a separate, explicit admin action).
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_invite_token
from dependencies import ROLE_TENANT_ADMIN
from services.tenants import PILOT_TENANT_IDS


@dataclass
class OnboardingResult:
    user_id: UUID
    email: str
    invite_token: str | None  # None when the account was already activated


async def onboard_tenant_admin(
    session: AsyncSession,
    *,
    tenant_id: str,
    tenant_name: str,
    tenant_type: str,
    country: str,
    admin_email: str,
    admin_name: str | None,
    geographic: bool,
) -> OnboardingResult:
    """Create/refresh the tenant's org + admin user and return an invite token.

    Does NOT commit — the caller commits as part of the registration txn.
    """
    email = admin_email.strip().lower()

    # 1) Organisation (upsert by the unique org_id slug). Access scope = which
    #    tenants this org may view (enforced by TenantContextMiddleware):
    #      * Geographic tenant (a State/Country) → scoped to ITSELF only.
    #      * Org partner (ECOWAS/NEMA/NGO…) → full access to all pilot regions.
    #    Finer per-partner region grants are a future enhancement.
    permitted = [tenant_id] if geographic else sorted(PILOT_TENANT_IDS)
    org_row = (await session.execute(
        text(
            """
            INSERT INTO public.organisations
                (org_id, name, type, country_iso, permitted_tenants)
            VALUES (:org_id, :name, :type, :country, :permitted)
            ON CONFLICT (org_id) DO UPDATE
              SET name = EXCLUDED.name, type = EXCLUDED.type,
                  permitted_tenants = EXCLUDED.permitted_tenants, updated_at = NOW()
            RETURNING id
            """
        ),
        {
            "org_id": tenant_id, "name": tenant_name, "type": tenant_type,
            "country": (country[:3] if country else None),
            "permitted": permitted,
        },
    )).first()
    org_uuid: UUID = org_row[0]

    # 2) Admin user. If one already exists for this email, reuse it; only issue a
    #    fresh invite when the account is still pending (not yet activated).
    existing = (await session.execute(
        text("SELECT id, is_active FROM public.users WHERE email = :e"),
        {"e": email},
    )).first()

    if existing is None:
        user_row = (await session.execute(
            text(
                """
                INSERT INTO public.users
                    (org_id, email, password_hash, role, full_name, is_active)
                VALUES (:org, :email, '', :role, :name, false)
                RETURNING id
                """
            ),
            {"org": org_uuid, "email": email, "role": ROLE_TENANT_ADMIN,
             "name": admin_name},
        )).first()
        user_uuid: UUID = user_row[0]
        return OnboardingResult(user_uuid, email, create_invite_token(user_uuid))

    user_uuid = existing[0]
    is_active = existing[1]
    # Keep the user attached to this org (handles a re-point) but don't disturb
    # an active account's password/state.
    await session.execute(
        text("UPDATE public.users SET org_id = :org WHERE id = :id"),
        {"org": org_uuid, "id": user_uuid},
    )
    token = None if is_active else create_invite_token(user_uuid)
    return OnboardingResult(user_uuid, email, token)
