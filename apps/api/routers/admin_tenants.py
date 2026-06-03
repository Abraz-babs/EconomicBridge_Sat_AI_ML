"""Super-admin tenant registry + module-entitlement endpoints.

Provisioning model: a super-admin registers tenants (after MoU/subscription)
and controls which modules each can access. Tenants do NOT self-register.

  GET   /admin/tenants                 — registry + per-tenant module matrix
  POST  /admin/tenants                 — register a tenant + its modules + invite
  PATCH /admin/tenants/{id}/modules    — set a tenant's enabled modules
  GET   /tenant-modules                — active tenant's enabled keys (nav, public)
  GET   /public-tenants                — minimal registry for the selector (public)

The /admin/* routes are gated by `require_super_admin` (Bearer JWT) — tenants and
anonymous callers get 401/403. Registering a tenant also provisions its schema
(geographic tenants), creates a pending tenant-admin account, and emails an
activation invite (see services/onboarding.py + services/email.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.engine import get_session
from dependencies import CurrentUser, require_super_admin
from schemas.envelope import ResponseMeta, SuccessResponse
from schemas.tenant_admin import (
    ModuleState,
    RegisteredTenant,
    TenantModulesData,
    TenantModulesPatch,
    TenantRegisterRequest,
    TenantRegistryData,
)
from services.modules import (
    MODULE_CATALOG,
    MODULE_KEYS,
    enabled_modules_for,
    invalidate_modules_cache,
)
from services.tenant_categories import (
    catalog as category_catalog,
    is_geographic,
    is_known_category,
)
from services.email import send_invite_email
from services.onboarding import onboard_tenant_admin
from services.tenant_provision import provision_tenant_schema, schema_exists
from services.tenants import register_runtime_tenant

router = APIRouter(tags=["admin-tenants"])
_LABELS = {m["key"]: m["label"] for m in MODULE_CATALOG}


def _trace_id(request: Request) -> UUID:
    # Always a fresh UUID — these control-plane endpoints don't need request
    # trace continuity, and reading request.state proved unreliable for the
    # no-dependency /tenant-modules handler.
    return uuid4()


def _catalog() -> list[dict[str, str]]:
    return [{"key": m["key"], "label": m["label"]} for m in MODULE_CATALOG]


@router.get("/admin/tenants", response_model=SuccessResponse[TenantRegistryData])
async def list_tenants(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[TenantRegistryData]:
    regs = (await session.execute(text(
        "SELECT id, name, tenant_type, country, status, subscription_tier, "
        "mou_reference, admin_email, created_at FROM public.tenant_registry ORDER BY id"
    ))).mappings().all()

    mod_rows = (await session.execute(text(
        "SELECT tenant_id, module_key, enabled FROM public.tenant_modules"
    ))).mappings().all()
    by_tenant: dict[str, dict[str, bool]] = {}
    for r in mod_rows:
        by_tenant.setdefault(r["tenant_id"], {})[r["module_key"]] = r["enabled"]

    tenants = [
        RegisteredTenant(
            id=r["id"], name=r["name"], tenant_type=r["tenant_type"],
            country=r["country"], status=r["status"],
            subscription_tier=r["subscription_tier"],
            mou_reference=r["mou_reference"], admin_email=r["admin_email"],
            created_at=r["created_at"],
            modules=[
                ModuleState(
                    key=m["key"], label=m["label"],
                    enabled=by_tenant.get(r["id"], {}).get(m["key"], False),
                )
                for m in MODULE_CATALOG
            ],
        )
        for r in regs
    ]
    return SuccessResponse(
        data=TenantRegistryData(
            tenants=tenants, catalog=_catalog(), categories=category_catalog(),
        ),
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )


@router.post("/admin/tenants", response_model=SuccessResponse[RegisteredTenant],
             status_code=status.HTTP_201_CREATED)
async def register_tenant(
    body: TenantRegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[RegisteredTenant]:
    unknown = set(body.enabled_keys) - MODULE_KEYS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown module key(s): {sorted(unknown)}")
    if not is_known_category(body.tenant_type):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown tenant category: {body.tenant_type!r}")

    geographic = is_geographic(body.tenant_type)
    # Geographic tenants (State/FCT/Country) hold data: auto-provision their
    # tenant_<id> schema and mark them a valid data tenant. Organization
    # tenants (NGO/Research/Funder/Federal) are access entities — registered +
    # entitled, but no geographic schema and not a data X-Tenant-Id.
    if geographic:
        if not await schema_exists(session, body.id):
            await provision_tenant_schema(session, body.id)
        register_runtime_tenant(body.id)

    admin_email = str(body.admin_email).strip().lower() if body.admin_email else None
    await session.execute(
        text(
            """
            INSERT INTO public.tenant_registry
                (id, name, tenant_type, country, status, subscription_tier,
                 mou_reference, admin_email, admin_name)
            VALUES (:id, :name, :ttype, :country, 'active', :tier, :mou, :aemail, :aname)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name, tenant_type = EXCLUDED.tenant_type,
                  country = EXCLUDED.country, subscription_tier = EXCLUDED.subscription_tier,
                  mou_reference = EXCLUDED.mou_reference,
                  admin_email = EXCLUDED.admin_email, admin_name = EXCLUDED.admin_name,
                  updated_at = NOW()
            """
        ),
        {"id": body.id, "name": body.name, "ttype": body.tenant_type,
         "country": body.country, "tier": body.subscription_tier, "mou": body.mou_reference,
         "aemail": admin_email, "aname": body.admin_name},
    )
    enabled = set(body.enabled_keys)
    for key in MODULE_KEYS:
        await session.execute(
            text(
                """
                INSERT INTO public.tenant_modules (tenant_id, module_key, enabled)
                VALUES (:t, :m, :en)
                ON CONFLICT (tenant_id, module_key) DO UPDATE
                  SET enabled = EXCLUDED.enabled, updated_at = NOW()
                """
            ),
            {"t": body.id, "m": key, "en": key in enabled},
        )

    # Onboarding: create the org + a pending tenant-admin user and mint an
    # activation invite. Done inside the same transaction so a failure here
    # rolls back the whole registration.
    invite_url: str | None = None
    onboard = None
    if admin_email:
        onboard = await onboard_tenant_admin(
            session,
            tenant_id=body.id, tenant_name=body.name, tenant_type=body.tenant_type,
            country=body.country, admin_email=admin_email, admin_name=body.admin_name,
            geographic=geographic,
        )

    await session.commit()
    invalidate_modules_cache(body.id)

    # Side effects after commit: send the invite email. In dev (console backend)
    # we echo the link back so the operator can copy it; in prod it's emailed and
    # never returned.
    if onboard and onboard.invite_token:
        settings = get_settings()
        invite_url = f"{settings.public_app_url}/activate?token={onboard.invite_token}"
        send_invite_email(
            to=onboard.email, tenant_name=body.name, activate_url=invite_url,
        )
        if settings.email_backend != "console":
            invite_url = None  # don't leak the link in the response in prod

    return await _one_tenant(session, request, body.id, invite_url=invite_url)


@router.patch("/admin/tenants/{tenant_id}/modules",
              response_model=SuccessResponse[RegisteredTenant])
async def set_tenant_modules(
    tenant_id: str,
    body: TenantModulesPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[RegisteredTenant]:
    unknown = set(body.enabled_keys) - MODULE_KEYS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown module key(s): {sorted(unknown)}")
    exists = (await session.execute(
        text("SELECT 1 FROM public.tenant_registry WHERE id = :t"), {"t": tenant_id}
    )).first()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown tenant {tenant_id!r}")

    enabled = set(body.enabled_keys)
    for key in MODULE_KEYS:
        await session.execute(
            text(
                """
                INSERT INTO public.tenant_modules (tenant_id, module_key, enabled)
                VALUES (:t, :m, :en)
                ON CONFLICT (tenant_id, module_key) DO UPDATE
                  SET enabled = EXCLUDED.enabled, updated_at = NOW()
                """
            ),
            {"t": tenant_id, "m": key, "en": key in enabled},
        )
    await session.commit()
    invalidate_modules_cache(tenant_id)
    return await _one_tenant(session, request, tenant_id)


@router.get("/tenant-modules", response_model=SuccessResponse[TenantModulesData])
async def tenant_modules(
    request: Request,
) -> SuccessResponse[TenantModulesData]:
    """Active tenant's enabled module keys — drives the dashboard nav."""
    tenant_id = (request.headers.get("X-Tenant-Id") or "").strip().lower()
    enabled = sorted(await enabled_modules_for(tenant_id)) if tenant_id else []
    return SuccessResponse(
        data=TenantModulesData(tenant_id=tenant_id, enabled=enabled, catalog=_catalog()),
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )


@router.get("/public-tenants", response_model=SuccessResponse[TenantRegistryData])
async def public_tenants(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[TenantRegistryData]:
    """PUBLIC, minimal registry for the dashboard tenant selector.

    Returns only id + tenant_type + status (no admin contact, no module matrix)
    so anonymous visitors can still see which registered geographic tenants are
    selectable. The sensitive admin view lives behind /admin/tenants.
    """
    regs = (await session.execute(text(
        "SELECT id, name, tenant_type, country, status, subscription_tier "
        "FROM public.tenant_registry WHERE status = 'active' ORDER BY id"
    ))).mappings().all()
    tenants = [
        RegisteredTenant(
            id=r["id"], name=r["name"], tenant_type=r["tenant_type"],
            country=r["country"], status=r["status"],
            subscription_tier=r["subscription_tier"], modules=[],
        )
        for r in regs
    ]
    return SuccessResponse(
        data=TenantRegistryData(tenants=tenants, catalog=[], categories=category_catalog()),
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )


async def _one_tenant(
    session: AsyncSession, request: Request, tenant_id: str, *,
    invite_url: str | None = None,
) -> SuccessResponse[RegisteredTenant]:
    r = (await session.execute(text(
        "SELECT id, name, tenant_type, country, status, subscription_tier, "
        "mou_reference, admin_email, created_at FROM public.tenant_registry WHERE id = :t"
    ), {"t": tenant_id})).mappings().first()
    mods = (await session.execute(text(
        "SELECT module_key, enabled FROM public.tenant_modules WHERE tenant_id = :t"
    ), {"t": tenant_id})).mappings().all()
    state = {m["module_key"]: m["enabled"] for m in mods}
    tenant = RegisteredTenant(
        id=r["id"], name=r["name"], tenant_type=r["tenant_type"], country=r["country"],
        status=r["status"], subscription_tier=r["subscription_tier"],
        mou_reference=r["mou_reference"], admin_email=r["admin_email"],
        created_at=r["created_at"], invite_url=invite_url,
        modules=[ModuleState(key=m["key"], label=m["label"],
                             enabled=state.get(m["key"], False)) for m in MODULE_CATALOG],
    )
    return SuccessResponse(
        data=tenant,
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )
