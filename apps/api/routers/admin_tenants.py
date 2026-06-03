"""Super-admin tenant registry + module-entitlement endpoints.

Provisioning model: a super-admin registers tenants (after MoU/subscription)
and controls which modules each can access. Tenants do NOT self-register.

  GET   /admin/tenants                 — registry + per-tenant module matrix
  POST  /admin/tenants                 — register a tenant + its modules
  PATCH /admin/tenants/{id}/modules    — set a tenant's enabled modules
  GET   /tenant-modules                — active tenant's enabled keys (nav)

NOTE: these admin routes are not yet behind real super-admin auth (the platform
has no auth layer yet — same as the other admin endpoints). Production must gate
them. New-tenant *schema provisioning* (CREATE SCHEMA + migrate + seed) is a
Phase-2 follow-up; POST here records the registry + entitlements.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
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
) -> SuccessResponse[TenantRegistryData]:
    regs = (await session.execute(text(
        "SELECT id, name, tenant_type, country, status, subscription_tier, "
        "mou_reference, created_at FROM public.tenant_registry ORDER BY id"
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
            mou_reference=r["mou_reference"], created_at=r["created_at"],
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
        data=TenantRegistryData(tenants=tenants, catalog=_catalog()),
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )


@router.post("/admin/tenants", response_model=SuccessResponse[RegisteredTenant],
             status_code=status.HTTP_201_CREATED)
async def register_tenant(
    body: TenantRegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[RegisteredTenant]:
    unknown = set(body.enabled_keys) - MODULE_KEYS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown module key(s): {sorted(unknown)}")

    # Phase 2: provision the data schema for a brand-new tenant (clone the
    # template schema). Existing pilot schemas are left untouched.
    if not await schema_exists(session, body.id):
        await provision_tenant_schema(session, body.id)
    register_runtime_tenant(body.id)  # accept it in is_valid_tenant_id now

    await session.execute(
        text(
            """
            INSERT INTO public.tenant_registry
                (id, name, tenant_type, country, status, subscription_tier, mou_reference)
            VALUES (:id, :name, :ttype, :country, 'active', :tier, :mou)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name, tenant_type = EXCLUDED.tenant_type,
                  country = EXCLUDED.country, subscription_tier = EXCLUDED.subscription_tier,
                  mou_reference = EXCLUDED.mou_reference, updated_at = NOW()
            """
        ),
        {"id": body.id, "name": body.name, "ttype": body.tenant_type,
         "country": body.country, "tier": body.subscription_tier, "mou": body.mou_reference},
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
    await session.commit()
    invalidate_modules_cache(body.id)

    return await _one_tenant(session, request, body.id, code_created=True)


@router.patch("/admin/tenants/{tenant_id}/modules",
              response_model=SuccessResponse[RegisteredTenant])
async def set_tenant_modules(
    tenant_id: str,
    body: TenantModulesPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
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


async def _one_tenant(
    session: AsyncSession, request: Request, tenant_id: str, *, code_created: bool = False,
) -> SuccessResponse[RegisteredTenant]:
    r = (await session.execute(text(
        "SELECT id, name, tenant_type, country, status, subscription_tier, "
        "mou_reference, created_at FROM public.tenant_registry WHERE id = :t"
    ), {"t": tenant_id})).mappings().first()
    mods = (await session.execute(text(
        "SELECT module_key, enabled FROM public.tenant_modules WHERE tenant_id = :t"
    ), {"t": tenant_id})).mappings().all()
    state = {m["module_key"]: m["enabled"] for m in mods}
    tenant = RegisteredTenant(
        id=r["id"], name=r["name"], tenant_type=r["tenant_type"], country=r["country"],
        status=r["status"], subscription_tier=r["subscription_tier"],
        mou_reference=r["mou_reference"], created_at=r["created_at"],
        modules=[ModuleState(key=m["key"], label=m["label"],
                             enabled=state.get(m["key"], False)) for m in MODULE_CATALOG],
    )
    return SuccessResponse(
        data=tenant,
        meta=ResponseMeta(tenant_id=None, trace_id=_trace_id(request),
                          timestamp=datetime.now(timezone.utc)),
    )
