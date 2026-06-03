"""Provision a brand-new tenant's data schema (Phase 2).

Registering a new tenant must create its `tenant_<id>` schema with the same
14 per-tenant tables (+ triggers) as the pilots. Rather than re-run the ~15
migrations' per-tenant DDL, we CLONE an existing tenant schema's structure:

  CREATE SCHEMA tenant_<id>;
  for each table in template:  CREATE TABLE … (LIKE template.t INCLUDING ALL);
  recreate each template trigger on the new schema.

`LIKE … INCLUDING ALL` copies columns, defaults, NOT NULL, CHECK constraints,
indexes and identity — everything except foreign keys (the per-tenant tables
don't rely on cross-schema FKs) and triggers (recreated explicitly). This is
DDL-agnostic, so it keeps working as new per-tenant tables are migrated in.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tenants import tenant_schema_name

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "kebbi"


async def schema_exists(session: AsyncSession, tenant_id: str) -> bool:
    schema = tenant_schema_name(tenant_id)
    row = await session.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
        {"s": schema},
    )
    return row.first() is not None


async def provision_tenant_schema(
    session: AsyncSession, tenant_id: str, *, template: str = DEFAULT_TEMPLATE,
) -> dict:
    """Create + populate the new tenant's schema by cloning `template`.

    Idempotent: CREATE SCHEMA/TABLE use IF NOT EXISTS and triggers use
    CREATE OR REPLACE, so re-provisioning is safe. Returns a small summary.
    """
    new_schema = tenant_schema_name(tenant_id)
    tmpl_schema = tenant_schema_name(template)

    await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{new_schema}"'))

    tables = (
        await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s ORDER BY table_name"
            ),
            {"s": tmpl_schema},
        )
    ).scalars().all()
    for t in tables:
        await session.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{new_schema}"."{t}" '
                f'(LIKE "{tmpl_schema}"."{t}" INCLUDING ALL)'
            )
        )

    trigger_defs = (
        await session.execute(
            text(
                """
                SELECT pg_get_triggerdef(t.oid)
                  FROM pg_trigger t
                  JOIN pg_class c ON c.oid = t.tgrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = :s AND NOT t.tgisinternal
                """
            ),
            {"s": tmpl_schema},
        )
    ).scalars().all()
    for ddl in trigger_defs:
        # Re-point schema + the tenant-prefixed trigger name, and make it
        # idempotent (PG14+ CREATE OR REPLACE TRIGGER).
        stmt = (
            ddl.replace(tmpl_schema, new_schema)
            .replace(f"trg_{template}_", f"trg_{tenant_id}_")
            .replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER", 1)
        )
        await session.execute(text(stmt))

    log.info(
        "provisioned tenant schema %s (%d tables, %d triggers) from %s",
        new_schema, len(tables), len(trigger_defs), tmpl_schema,
    )
    return {"schema": new_schema, "tables": len(tables), "triggers": len(trigger_defs)}
