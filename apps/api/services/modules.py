"""Module catalog + per-tenant entitlement lookups.

A tenant only accesses the modules a super-admin has enabled for it
(public.tenant_modules). This module is the single source of truth for:
  * the canonical module list (key + label) — used by the admin UI,
  * the request-path -> module mapping — used by the enforcement middleware,
  * `enabled_modules_for(tenant_id)` — the cached entitlement set.

Fail-open: a tenant with NO rows in tenant_modules (e.g. not yet registered)
gets ALL modules, so the control plane never locks out an existing tenant by
omission. Lock-out is an explicit `enabled = FALSE`, never an absence.
"""
from __future__ import annotations

import time

from sqlalchemy import text

from db.engine import get_session_factory


# Canonical modules. `key` matches the frontend nav tab id.
MODULE_CATALOG: list[dict[str, str]] = [
    {"key": "economic-visibility", "label": "Poverty Mapping (Economic Visibility)"},
    {"key": "aid-coordination", "label": "Aid Coordination Bridge"},
    {"key": "farmland", "label": "Farmland Protection"},
    {"key": "cropguard", "label": "Agriculture (CropGuard)"},
    {"key": "shockguard", "label": "Disaster Relief (ShockGuard)"},
    {"key": "mobility-compass", "label": "Mobility Compass"},
    {"key": "skillsbridge", "label": "SkillsBridge"},
]
MODULE_KEYS: frozenset[str] = frozenset(m["key"] for m in MODULE_CATALOG)

# First path segment after /api/v1 -> module key (for the enforcement
# middleware). Paths not listed here are control-plane / always-on (overview,
# admin, health, tenant-info, intelligence, dpa, …) and are never module-gated.
PATH_PREFIX_TO_MODULE: dict[str, str] = {
    "economic_visibility": "economic-visibility",
    "aid_coordination": "aid-coordination",
    "farmland": "farmland",
    "cropguard": "cropguard",
    "cropguard_ndvi": "cropguard",
    "shockguard": "shockguard",
    "economic_mobility": "mobility-compass",
    "skills": "skillsbridge",
}


_CACHE: dict[str, tuple[frozenset[str], float]] = {}
_TTL_SECONDS = 30.0


def invalidate_modules_cache(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(tenant_id, None)


async def enabled_modules_for(tenant_id: str) -> frozenset[str]:
    """Set of module keys this tenant may access. Cached for `_TTL_SECONDS`.

    Returns ALL modules when the tenant has no rows (fail-open — see module
    docstring). Lock-out requires an explicit enabled=FALSE row.
    """
    now = time.monotonic()
    hit = _CACHE.get(tenant_id)
    if hit and hit[1] > now:
        return hit[0]

    factory = get_session_factory()
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT module_key FROM public.tenant_modules "
                "WHERE tenant_id = :t AND enabled = TRUE"
            ),
            {"t": tenant_id},
        )
        has_any = await session.execute(
            text("SELECT 1 FROM public.tenant_modules WHERE tenant_id = :t LIMIT 1"),
            {"t": tenant_id},
        )
        keys = {r[0] for r in rows.all()}
        if has_any.first() is None:
            keys = set(MODULE_KEYS)  # unregistered -> all

    result = frozenset(keys)
    _CACHE[tenant_id] = (result, now + _TTL_SECONDS)
    return result
