"""Schemas for super-admin tenant registry + module entitlement endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ModuleState(BaseModel):
    key: str
    label: str
    enabled: bool


class RegisteredTenant(BaseModel):
    id: str
    name: str
    tenant_type: str
    country: str
    status: str
    subscription_tier: str
    mou_reference: str | None = None
    created_at: datetime | None = None
    modules: list[ModuleState]


class TenantRegistryData(BaseModel):
    tenants: list[RegisteredTenant]
    catalog: list[dict[str, str]]   # [{key,label}, …]
    categories: list[dict] = []     # [{key,label,group,geographic}, …]


class TenantModulesPatch(BaseModel):
    """Set the full enabled-module set for a tenant (super-admin)."""
    enabled_keys: list[str]


class TenantRegisterRequest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=200)
    tenant_type: str = "ng_state"
    country: str = "nigeria"
    subscription_tier: str = "standard"
    mou_reference: str | None = Field(default=None, max_length=200)
    enabled_keys: list[str] = Field(default_factory=list)


class TenantModulesData(BaseModel):
    """What the dashboard reads to filter the nav for the active tenant."""
    tenant_id: str
    enabled: list[str]
    catalog: list[dict[str, str]]
