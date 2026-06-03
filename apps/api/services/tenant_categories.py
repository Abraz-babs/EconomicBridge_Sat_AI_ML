"""Tenant category taxonomy.

A tenant is registered under one category. Two groups:

  * Government  — geographic data tenants (hold satellite/economic data, get a
    provisioned tenant_<id> schema): Nigerian State, FCT, ECOWAS Country; plus
    Federal Ministry/Agency (national-scope, NOT geographic — accesses data
    across the country's states).
  * Organization — access entities (NGO, Research institute, Funder). They
    subscribe to modules and view data, but don't hold their own geographic
    schema.

`geographic=True` is the gate for auto-provisioning a data schema and for being
a valid data X-Tenant-Id. Non-geographic tenants are recorded + entitled but
don't get a schema.
"""
from __future__ import annotations

TENANT_CATEGORIES: list[dict] = [
    {"key": "ng_state", "label": "Nigerian State", "group": "Government", "geographic": True},
    {"key": "ng_fct", "label": "FCT (Abuja)", "group": "Government", "geographic": True},
    {"key": "ecowas_country", "label": "ECOWAS Country", "group": "Government", "geographic": True},
    {"key": "ng_federal", "label": "Federal Ministry / Agency (Nigeria)", "group": "Government", "geographic": False},
    {"key": "ngo", "label": "NGO / Aid Organization", "group": "Organization", "geographic": False},
    {"key": "research", "label": "Research Institute", "group": "Organization", "geographic": False},
    {"key": "funder", "label": "Funding Organization", "group": "Organization", "geographic": False},
]

CATEGORY_KEYS: frozenset[str] = frozenset(c["key"] for c in TENANT_CATEGORIES)
_GEOGRAPHIC: frozenset[str] = frozenset(c["key"] for c in TENANT_CATEGORIES if c["geographic"])


def is_known_category(key: str) -> bool:
    return key in CATEGORY_KEYS


def is_geographic(category: str) -> bool:
    """True if this category holds geographic data (gets a schema + is a valid
    data tenant). Unknown categories default to geographic for safety."""
    return category in _GEOGRAPHIC or category not in CATEGORY_KEYS


def catalog() -> list[dict]:
    return [dict(c) for c in TENANT_CATEGORIES]
