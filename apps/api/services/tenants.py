"""Tenant registry — pure functions, no DB access.

Source of truth: tenants.yaml at the repo root. To keep Step 6 dependency-free we
embed the pilot allowlist as a Python constant here; once we need richer tenant
metadata (capital, language, ROI) at request time we'll switch this module to
parse tenants.yaml on startup.

`PILOT_TENANT_IDS` are the 6 Nigerian states with `active: true` in tenants.yaml
plus the FCT, plus the first two ECOWAS pilots (Ghana, Senegal). Any tenant not
in this set is rejected by the middleware as 404.

The schema name convention is `tenant_{id}` (CLAUDE.md §10, ADR-001).
"""
from __future__ import annotations

import re

PILOT_TENANT_IDS: frozenset[str] = frozenset(
    {
        "kebbi",
        "benue",
        "plateau",
        "kaduna",
        "niger",
        "zamfara",
        "nasarawa",
        "fct",
        "ghana",
        "senegal",
    }
)

# Defensive — even after allowlist validation we use this to compose the schema
# name. Any allowlisted ID that doesn't match this pattern is a programming
# error and we fail loudly rather than risk SQL injection.
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{1,49}$")


# Tenants registered at runtime (Phase 2): a super-admin can provision tenants
# beyond the hardcoded pilots. Populated at startup from public.tenant_registry
# and on registration. Per-process (dev = single worker); a multi-worker
# deployment should reload this periodically.
_DYNAMIC_TENANT_IDS: set[str] = set()


def is_valid_tenant_id(tenant_id: str | None) -> bool:
    """True iff `tenant_id` is a pilot OR a runtime-registered tenant."""
    if not tenant_id:
        return False
    return tenant_id in PILOT_TENANT_IDS or tenant_id in _DYNAMIC_TENANT_IDS


def register_runtime_tenant(tenant_id: str) -> None:
    """Mark a newly-registered tenant id as valid for this process."""
    if _SAFE_ID.match(tenant_id):
        _DYNAMIC_TENANT_IDS.add(tenant_id)


def set_runtime_tenants(tenant_ids) -> None:
    """Replace the runtime-registered set (called at startup from the DB)."""
    _DYNAMIC_TENANT_IDS.clear()
    _DYNAMIC_TENANT_IDS.update(t for t in tenant_ids if _SAFE_ID.match(t))


def tenant_schema_name(tenant_id: str) -> str:
    """Return the Postgres schema name for the given tenant ID.

    Raises ValueError if the ID would not be safe to interpolate as an identifier.
    Use this AFTER validating against the allowlist.
    """
    if not _SAFE_ID.match(tenant_id):
        raise ValueError(f"unsafe tenant_id: {tenant_id!r}")
    return f"tenant_{tenant_id}"


__all__ = [
    "PILOT_TENANT_IDS",
    "is_valid_tenant_id",
    "tenant_schema_name",
    "register_runtime_tenant",
    "set_runtime_tenants",
]
