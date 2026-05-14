# ADR-001: PostgreSQL Schema-Per-Tenant Isolation

**Status:** Accepted  
**Date:** March 2026  
**Deciders:** Abdullahi Zuru Ibrahim (Platform Architect)  
**Operated by:** Bizra Farms Integrated Nigeria Limited

---

## Context

EconomicBridge serves 52 tenants: 36 Nigerian states, the FCT, and 15 ECOWAS
countries. Each tenant is a sovereign government entity or international
organisation with strict data sovereignty requirements. A government in Kebbi State
must be physically incapable of accessing data belonging to Kaduna State, and vice
versa. This is not a UI restriction — it must be enforced at the database layer.

Three PostgreSQL multi-tenancy strategies were evaluated:
1. Separate databases per tenant
2. Shared database, shared schema (row-level security via tenant_id column)
3. Shared database, schema-per-tenant (PostgreSQL search_path isolation)

---

## Decision

**Schema-per-tenant isolation (Option 3).**

Each tenant gets a dedicated PostgreSQL schema within a single RDS instance:
- `tenant_kebbi`
- `tenant_kaduna`
- `tenant_ghana`
- `tenant_shared` (read-only reference data accessible to all)

The application sets `SET search_path = tenant_{id}` at the start of every
database connection via the TenantContext middleware. All queries then execute
within that schema. Cross-schema queries are structurally impossible unless
explicitly constructed — and the application layer contains no code to do so
except the bilateral_agreement pathway which requires a flag check.

---

## Consequences

### Positive
- Data sovereignty enforced at database layer — not application logic
- Government IT auditors can verify isolation by inspecting schema structure
- Adding a new tenant is a migration only — no application code change
- Performance: per-schema indexes tuned to tenant data volume
- Backup and restore can be performed per-tenant (pg_dump -n tenant_kebbi)
- NDPA 2023 compliance: data residency verifiable at schema level

### Negative
- Schema migrations must be applied to all 52 schemas (handled by Alembic
  multi-tenant migration runner in scripts/run_migrations.py)
- Connection pooling requires search_path reset on connection checkout
  (handled by PgBouncer configuration — pool_mode=session)
- Slightly higher schema management overhead vs row-level security

### Neutral
- 52 schemas on a single RDS instance is well within PostgreSQL limits
  (tested to 10,000+ schemas without performance degradation)

---

## Rejected Alternatives

**Separate databases:** Operationally expensive — 52 RDS instances, 52 connection
pools, 52 backup schedules. Cost-prohibitive at fellowship stage.

**Shared schema, row-level security:** Simpler to operate but harder to audit.
A bug in the RLS policy exposes all tenant data simultaneously. Government
auditors cannot visually verify isolation. Failed NDPA 2023 risk assessment.

---

## Implementation Notes

- TenantContext middleware: `apps/api/middleware/tenant.py`
- Migration runner: `scripts/run_migrations.py --all-tenants`
- Tenant provisioning: `scripts/generate_tenant.py --tenant-id kebbi`
- PgBouncer config: `infrastructure/pgbouncer/pgbouncer.ini`
