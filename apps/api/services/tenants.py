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


def is_valid_tenant_id(tenant_id: str | None) -> bool:
    """Return True iff `tenant_id` is in the allowlist."""

    if not tenant_id:
        return False
    return tenant_id in PILOT_TENANT_IDS


def tenant_schema_name(tenant_id: str) -> str:
    """Return the Postgres schema name for the given tenant ID.

    Raises ValueError if the ID would not be safe to interpolate as an identifier.
    Use this AFTER validating against the allowlist.
    """
    if not _SAFE_ID.match(tenant_id):
        raise ValueError(f"unsafe tenant_id: {tenant_id!r}")
    return f"tenant_{tenant_id}"


__all__ = ["PILOT_TENANT_IDS", "is_valid_tenant_id", "tenant_schema_name"]
