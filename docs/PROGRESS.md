# EconomicBridge — Progress & Continuation Playbook

> **Purpose.** This document captures every meaningful build step from project inception through today, what is currently working, and the exact next steps to take. If you carry this project to another IDE or hand it to a fresh AI agent, this file plus [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](../CLAUDE.md) is all you need to continue without re-discovery.

**Snapshot date:** 2026-05-11
**Current stage:** Pre-production — Next.js dashboard v0.3 live locally, backend not yet started
**Active working directory:** `economic-bridge-project/`

---

## 1. Where We Started

| Asset | Status before this project | Inherited capability |
|-------|---------------------------|----------------------|
| Sentinel National Intelligence Engine | Deployed | 36 NG states + FCT satellite coverage |
| Citadel Kebbi State Security Dashboard | Deployed & live | Random Forest conflict prediction proven |
| EconomicBridge prototype v0.3 (HTML) | Deployed to GitHub Pages | UI/UX specification we must match |

EconomicBridge production build inherits the proven patterns from Citadel Kebbi. The HTML prototype defines the visual/UX target.

---

## 2. What Has Been Built So Far (chronological)

### Phase 0 — Foundations (March 2026)

1. **Repository scaffolding** in `economic-bridge-project/`
   - `CLAUDE.md` — full AI session contract (14 sections, conventions, rules)
   - `.cursorrules` — Cursor IDE behaviour rules
   - `README.md`, `Makefile`, `docker-compose.yml`, `alembic.ini`
   - Project structure carved out: `apps/{api,frontend,ingestion,ml}/`, `infrastructure/`, `migrations/`, `docs/`, `scripts/`, `prompts/`

2. **Tenant registry** — `tenants.yaml` populated with all 52 tenants
   (36 Nigerian states + FCT + 15 ECOWAS countries) including ROI bounding boxes, SMS gateway preference, language, and deployment phase

3. **Infrastructure observability skeleton**
   - [infrastructure/prometheus/prometheus.yml](../infrastructure/prometheus/prometheus.yml) + alert rules
   - [infrastructure/grafana/](../infrastructure/grafana/) datasource + dashboards manifests

4. **First ADR** — [ADR-001 Schema-per-tenant isolation](decisions/ADR-001-tenant-isolation.md) accepted and documented

5. **Operational scripts (stubs)**
   - [scripts/generate_tenant.py](../scripts/generate_tenant.py) — tenant provisioning
   - [scripts/validate_tenant.py](../scripts/validate_tenant.py) — tenants.yaml validator
   - [scripts/run_migrations.py](../scripts/run_migrations.py) — multi-tenant Alembic runner
   - [scripts/init_db.sql](../scripts/init_db.sql) — extensions + base schema
   - [scripts/deploy.sh](../scripts/deploy.sh)

### Phase 1 — Frontend production app (March 2026 → today)

The Next.js dashboard at [apps/frontend/](../apps/frontend/) is the only currently-running service. Built with `next@16.1.7`, React 19, TypeScript strict mode.

**Pages**

- [src/app/page.tsx](../apps/frontend/src/app/page.tsx) — single-page dashboard with tabbed navigation
- [src/app/layout.tsx](../apps/frontend/src/app/layout.tsx) — root layout
- [src/app/globals.css](../apps/frontend/src/app/globals.css) — full design system as CSS variables + utility classes

**Role-based access control**

- [src/context/RoleContext.tsx](../apps/frontend/src/context/RoleContext.tsx) — Context provider
- [src/data/roles.ts](../apps/frontend/src/data/roles.ts) — 5 roles defined (NGO, Gov, UN/WB, Research, Admin)
- [src/components/RoleSwitcher.tsx](../apps/frontend/src/components/RoleSwitcher.tsx) — top-of-page role chooser
- [src/components/PermissionBanner.tsx](../apps/frontend/src/components/PermissionBanner.tsx) — RBAC notice
- [src/components/DataAccessMatrix.tsx](../apps/frontend/src/components/DataAccessMatrix.tsx) — visualises matrix

**Overview tab components**

- [Header.tsx](../apps/frontend/src/components/Header.tsx) — brand, role pill, live UTC clock
- [Navigation.tsx](../apps/frontend/src/components/Navigation.tsx) — tab navigation
- [AlertBar.tsx](../apps/frontend/src/components/AlertBar.tsx) — rotating priority alerts
- [StatsRow.tsx](../apps/frontend/src/components/StatsRow.tsx) — 4 KPI tiles
- [SatelliteMap.tsx](../apps/frontend/src/components/SatelliteMap.tsx) — map placeholder (Mapbox/Deck.gl pending)
- [IntelligenceFeed.tsx](../apps/frontend/src/components/IntelligenceFeed.tsx)
- [CoverageTrend.tsx](../apps/frontend/src/components/CoverageTrend.tsx)
- [CropHealthIndex.tsx](../apps/frontend/src/components/CropHealthIndex.tsx)
- [ActiveResponse.tsx](../apps/frontend/src/components/ActiveResponse.tsx)
- [SystemStatus.tsx](../apps/frontend/src/components/SystemStatus.tsx)
- [Footer.tsx](../apps/frontend/src/components/Footer.tsx)

**Module 03 — Farmland Protection (LIVE)**

- [src/components/farmland/FarmlandPanel.tsx](../apps/frontend/src/components/farmland/FarmlandPanel.tsx) — SAR heat overlay, encroachment alerts, conflict prediction timeline (mocked data, ready for backend wiring)

**Admin panel**

- [src/components/admin/AdminPanel.tsx](../apps/frontend/src/components/admin/AdminPanel.tsx) — visible only to `admin` role

**Module stubs (Q2 & Q3)**

- [src/components/stubs/ModuleStub.tsx](../apps/frontend/src/components/stubs/ModuleStub.tsx) — reused for Modules 01, 02, 04, 05, 06, 07. Each declares its quarter, data sources, and capabilities.

**Resilience**

- [src/components/ErrorBoundary.tsx](../apps/frontend/src/components/ErrorBoundary.tsx) — wraps every section so one module crash never takes down the dashboard
- Accessibility: skip-link, ARIA labels on header, `role="main"` landmark, `suppressHydrationWarning` on the live clock

### Phase 2 — Backend scaffold (March 2026, minimal)

- [apps/api/VERSION](../apps/api/VERSION)
- [apps/api/core/database.py](../apps/api/core/database.py) — placeholder
- No routers, services, repositories, or middleware yet

### Phase 3 — Cleanup (this session, 2026-05-11)

- Removed every "Bergel Institute" / "Fellowship FT1" reference from source files. Build artefacts under `.next/` still contain old strings — they regenerate on the next `npm run build` / `npm run dev`.
- Files updated: `apps/frontend/src/components/Header.tsx`, `apps/frontend/src/components/Footer.tsx`, `README.md`, `CLAUDE.md`, `docs/ROADMAP.md`, `docs/decisions/ADR-001-tenant-isolation.md`, `.cursorrules`, `economicbridge-new/economicbridge-new-files/README.md`, `economicbridge-new/economicbridge-new-files/scripts/init_db.sql`.
- Created [docs/ARCHITECTURE.md](ARCHITECTURE.md) (this document's companion).
- Created [docs/PROGRESS.md](PROGRESS.md) (this file).

---

## 3. What Currently Works

| Capability | Where | How to verify |
|------------|-------|---------------|
| Multi-role dashboard | `apps/frontend` | `npm run dev` → http://localhost:3000 → switch role |
| Tab navigation (Overview, Farmland, Admin, 5 stubs) | `page.tsx` | Click each tab |
| Error isolation (one module crash ≠ page crash) | `ErrorBoundary` wraps every panel | Throw in a component → only that panel shows fallback |
| Admin-only visibility | `page.tsx:83` | Admin tab only renders when role === 'admin' |
| Live UTC clock | `Header.tsx` | Visible top right |
| Farmland Protection demo view | `FarmlandPanel.tsx` | Click "farmland" tab |
| 52-tenant registry | `tenants.yaml` | YAML parses; pilot states have `active: true` |

---

## 4. What Does NOT Work Yet

- **Backend** — no FastAPI app running, no DB, no auth
- **Satellite ingestion** — none of Copernicus/FIRMS/N2YO/EarthEngine wired up
- **ML services** — no models trained or served
- **Real map** — `SatelliteMap` is a styled div, not Mapbox + Deck.gl
- **Real data** — every panel renders hardcoded/mock data
- **Auth** — no JWT, no login screen, no session
- **AWS** — no account configured, no Terraform applied
- **CI/CD** — no GitHub Actions workflow committed
- **Tests** — no test files committed for backend or frontend yet
- **Migrations** — `migrations/` directory exists but no migration files

---

## 5. What's Next (prioritised continuation list)

Work top-down. Do not skip ahead — each step assumes the previous one is done.

### Step 1 — Verify baseline (5 minutes)

```bash
cd economic-bridge-project/apps/frontend
npm install
npm run dev
```

Open http://localhost:3000. Switch roles. Click every tab. Confirm the dashboard renders without console errors. If something is broken, fix it before moving on.

### Step 2 — Wire Mapbox into SatelliteMap (Q1 task) ✅ **DONE 2026-05-11**

Delivered:
- `mapbox-gl@3.23.1` and `deck.gl@9.3.2` installed; `postcss` override pinned to keep audit clean
- [apps/frontend/src/data/tenants.ts](../apps/frontend/src/data/tenants.ts) — typed catalogue of all 52 tenants (37 Nigeria + 15 ECOWAS) with centroid derived from `satellite_roi`, plus `RISK_RGB` / `RISK_HEX` color maps and `KEBBI_CENTER` constant
- [apps/frontend/src/components/SatelliteMap.tsx](../apps/frontend/src/components/SatelliteMap.tsx) — rewritten: mapbox-gl base (style `dark-v11`) centred on Kebbi at zoom 5.2, Deck.gl `ScatterplotLayer` for tenants via `MapboxOverlay`. Marker radius reflects `active` status, fill color reflects `conflict_risk`. Clicking a marker pins it to the detail strip. Layer toggle filters: `Disaster` → critical+high only; others → all 52
- [apps/frontend/src/components/farmland/FarmlandMap.tsx](../apps/frontend/src/components/farmland/FarmlandMap.tsx) — **new** map for Module 03. Same Mapbox base centred on NW Nigeria + middle belt at zoom 5.7. Deck.gl `HeatmapLayer` over alert points with severity-weighted intensity + `ScatterplotLayer` pins. Layer toggle (`Heat` / `NDVI` / `SAR` / `Boundaries`) controls heatmap visibility
- [apps/frontend/src/components/farmland/FarmlandPanel.tsx](../apps/frontend/src/components/farmland/FarmlandPanel.tsx) — SVG illustration replaced with `<FarmlandMap />`. Alerts data extended with real LGA coordinates: Argungu (12.74°N, 4.53°E), Anka (12.11°N, 5.93°E), Shendam (8.88°N, 9.54°E), Kachia (9.87°N, 7.95°E), Birnin Kebbi resolved (12.45°N, 4.20°E)
- Three overlay states on each map: `no-token` (clear instructions), `loading`, `error` — non-blocking, never crash the panel
- Mapbox CSS injected via `<link>` tag once on mount — no bundler asset friction
- [apps/frontend/.env.local.example](../apps/frontend/.env.local.example) documenting `NEXT_PUBLIC_MAPBOX_TOKEN`
- `.env.local` populated with the project's Mapbox public token (gitignored via `.env*` rule in `.gitignore`)
- Static styles moved into [globals.css](../apps/frontend/src/app/globals.css) (`.map-canvas`, `.map-overlay*`, `.ldot[data-risk-color="..."]`, `.map-detail-*`, `.fp-legend-dot--*`).

Verified: Next.js 16.2.6, `Ready in 1078ms`, `GET / 200`. Both Overview and Farmland tabs render real Mapbox tiles. Without a token both panels fall back to a clear placeholder — no crash.

### Step 3 — Bootstrap FastAPI backend ✅ **DONE 2026-05-11**

Delivered (minimal scope — DB and JWT auth deferred to Steps 4 / 5):
- [apps/api/main.py](../apps/api/main.py) — FastAPI app, OpenAPI mounted at `/api/docs` and `/api/openapi.json`, middleware stack registered (Trace → Security → Tenant stub → Audit stub → CORS), health router wired at `/api/v1/health`
- [apps/api/config.py](../apps/api/config.py) — `Settings` via pydantic-settings, sourced from env + `.env`. Production secrets must come from AWS Secrets Manager (CLAUDE.md §4.1 — not env vars)
- [apps/api/dependencies.py](../apps/api/dependencies.py) — `require_authenticated_user` placeholder that 501s until JWT auth lands
- [apps/api/schemas/envelope.py](../apps/api/schemas/envelope.py) — generic `SuccessResponse[T]` / `ErrorResponse` / `ResponseMeta` / `Pagination` / `ErrorDetail` matching CLAUDE.md §7 exactly
- [apps/api/middleware/trace.py](../apps/api/middleware/trace.py) — generates a per-request `trace_id` (UUID4), stamps `X-Trace-Id` response header, exposes via `request.state.trace_id`
- [apps/api/middleware/security.py](../apps/api/middleware/security.py) — adds `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security`, `Permissions-Policy` to every response
- [apps/api/middleware/tenant.py](../apps/api/middleware/tenant.py) — STUB. Documents the JWT extraction + `SET search_path` work due in Step 5/6 (ADR-001, CLAUDE.md §4.2). Sets `request.state.tenant_id = None`
- [apps/api/middleware/audit.py](../apps/api/middleware/audit.py) — STUB. Logs every POST/PUT/PATCH/DELETE to stdout. Real audit log INSERTs arrive with the DB in Step 4 (CLAUDE.md §4.6, §6)
- [apps/api/routers/health.py](../apps/api/routers/health.py) — `GET /api/v1/health` returns `SuccessResponse[HealthData]` with `{status, service, version, app_env}` in `data`
- [apps/api/tests/test_health.py](../apps/api/tests/test_health.py) — 6 tests covering envelope shape, trace_id flow, security headers, per-request trace_id uniqueness. All pass.
- [apps/api/tests/conftest.py](../apps/api/tests/conftest.py) — prepends `apps/api/` to `sys.path` so imports resolve regardless of pytest invocation dir
- [apps/api/requirements.txt](../apps/api/requirements.txt) + [apps/api/requirements-dev.txt](../apps/api/requirements-dev.txt) + [apps/api/pytest.ini](../apps/api/pytest.ini) + [apps/api/.env.example](../apps/api/.env.example)

Verified:
```
pytest -v       → 6 passed in 2.21s
uvicorn main:app --port 8000
GET /api/v1/health → 200, envelope matches CLAUDE.md §7 exactly, X-Trace-Id header matches meta.trace_id
```

**Deviation from CLAUDE.md:** Python 3.12.2 used instead of 3.11 because 3.11 isn't installed on this machine. Functionally identical for FastAPI / Pydantic / SQLAlchemy.

**Run commands (Windows PowerShell):**
```powershell
cd apps/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Tests:
.\.venv\Scripts\python.exe -m pytest -v
# Dev server:
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
# Swagger UI: http://localhost:8000/api/docs
```

### Step 4 — Local Postgres + first migration ✅ **DONE 2026-05-12**

Delivered:
- Postgres 15 + PostGIS installed natively (EDB installer); Docker deferred. Database `economicbridge` created on `localhost:5432`
- [apps/api/db/engine.py](../apps/api/db/engine.py) — async SQLAlchemy engine + `async_sessionmaker` + `get_session` FastAPI dependency (commit-on-success / rollback-on-exception)
- [apps/api/db/base.py](../apps/api/db/base.py) — `DeclarativeBase` root for all ORM models
- [apps/api/models/](../apps/api/models/) — `Organisation`, `User`, `RefreshToken`, `AuditLog` (the four public-schema tables), plus `mixins.py` with `UUIDPrimaryKeyMixin` and `TimestampMixin`
- [apps/api/alembic.ini](../apps/api/alembic.ini) + [apps/api/migrations/env.py](../apps/api/migrations/env.py) — Alembic wired to load the sync URL from `config.Settings.database_url_sync`; never reads URLs from the ini file
- [apps/api/migrations/versions/0001_create_users_and_audit_log.py](../apps/api/migrations/versions/0001_create_users_and_audit_log.py) — hand-rolled baseline (more predictable than autogenerate for this size). Creates extensions (`uuid-ossp`, `pgcrypto`, optional `postgis`/`timescaledb`), `update_updated_at()` trigger function + triggers, all four tables with indexes, INSERT-only RULES on `audit_log`, and optional TimescaleDB hypertable conversion guarded by an `IF EXISTS` check
- [apps/api/routers/health_db.py](../apps/api/routers/health_db.py) — `GET /api/v1/health/db` returns server version + extension presence, mounted on the API; 503 with `DATABASE_UNREACHABLE` error on failure
- [apps/api/tests/test_health_db.py](../apps/api/tests/test_health_db.py) — marked `@pytest.mark.integration`. Default pytest run excludes them via `pytest.ini`'s `addopts = -m "not integration"`. Run with `pytest -m integration` against a live DB.
- Added to [apps/api/requirements.txt](../apps/api/requirements.txt): `sqlalchemy[asyncio]`, `asyncpg`, `psycopg2-binary` (for Alembic's sync driver), `alembic`, `greenlet`, `geoalchemy2`

Verified:
```
alembic heads             → 0001 (head)
alembic upgrade head      → applied
pytest -v                 → 6 passed, 2 deselected
GET /api/v1/health/db     → 200 with server_version + extension flags
```

**Note:** `econbridge_app` / `econbridge_readonly` roles from `scripts/init_db.sql` are NOT created by this migration — the app connects as the `postgres` superuser in dev. That role separation lands when we provision a non-dev environment.

### Step 5 — JWT auth + login gate ❌ **REMOVED 2026-05-12**

**Product decision:** the dashboard is openly accessible at its URL — no login wall. Authentication is reserved for paid / monetized modules and for designated free-tier organisations. Anonymous visitors should land on the dashboard immediately; the role-switcher remains a demo affordance.

Reverted in this session:
- Frontend: deleted `lib/api.ts`, `context/AuthContext.tsx`, `components/auth/LoginScreen.tsx`. Restored `RoleContext.tsx` to its pre-Step-5 form (default `ngo`). Restored `RoleSwitcher.tsx` to plain role buttons (no Sign-in / Sign-out). Restored `page.tsx` to render the dashboard directly under `RoleProvider`. Removed the login-screen / logout-button CSS from `globals.css`. Removed `http://localhost:8000` from `next.config.ts` `connect-src`. Restored `.env.local.example`.
- Backend: deleted `services/auth.py`, `repositories/users.py`, `repositories/refresh_tokens.py`, `schemas/auth.py`, `routers/auth.py`, `scripts/seed_dev_user.py`, `tests/test_auth.py`. Restored `dependencies.py` to the 501 stub. Removed JWT settings from `config.py` and `.env.example`. Removed `passlib`, `python-jose`, `email-validator` from `requirements.txt`.

What this means going forward: when the **monetized modules** (CropGuard alerts SMS, partner data exports, etc.) are introduced, auth re-enters as a per-feature CTA — not a global gate. The auth machinery can be partially reintroduced then (much of the deleted code lives in git history). Free-tier "designated organisation" accounts use the same auth, distinguished by role/tier flag.

### Step 6 — TenantContext middleware ✅ **DONE 2026-05-12**

Tenant identification is **header-based** now that the JWT layer is gone (Step 5 was removed in favour of open access). Frontend (or any client) passes `X-Tenant-Id: <slug>`; the middleware validates against an allowlist and the DB session pins `search_path` to that tenant's schema for the request.

Delivered:
- [apps/api/services/tenants.py](../apps/api/services/tenants.py) — `PILOT_TENANT_IDS` allowlist (6 NG pilot states + FCT + Ghana + Senegal), `is_valid_tenant_id()`, `tenant_schema_name()` with regex guard against unsafe identifiers
- [apps/api/middleware/tenant.py](../apps/api/middleware/tenant.py) — STUB replaced with real implementation. Reads `X-Tenant-Id`, lowercases it, validates against the allowlist. Stamps `request.state.tenant_id`. Returns 404 `TENANT_NOT_FOUND` envelope (with trace_id preserved) for unknown tenants. Header is optional — missing means tenant-agnostic
- [apps/api/db/engine.py](../apps/api/db/engine.py) `get_session` now accepts `Request` and runs `SET search_path TO tenant_<id>, public` on the session before yielding. Defense-in-depth: tenant_id is re-validated against the allowlist before the SET to keep the f-string interpolation safe
- [apps/api/routers/tenants.py](../apps/api/routers/tenants.py) — `GET /api/v1/tenant-info` echoes `tenant_id`, `current_schema()`, and `SHOW search_path` so callers + tests can confirm the scoping is in effect
- [apps/api/migrations/versions/0002_create_pilot_tenant_schemas.py](../apps/api/migrations/versions/0002_create_pilot_tenant_schemas.py) — provisions `tenant_kebbi`, `tenant_benue`, `tenant_plateau`, `tenant_kaduna`, `tenant_niger`, `tenant_zamfara`, `tenant_fct`, `tenant_ghana`, `tenant_senegal` schemas, each with a smoke-test `widgets` table. Real per-tenant tables arrive when their modules land (alert_events in Step 7, etc.)
- [apps/api/tests/test_tenant_context.py](../apps/api/tests/test_tenant_context.py) — 5 integration tests covering: tenant-info without header (public schema), with valid header (tenant schema), with unknown header (404), header case-insensitive normalization, and the cross-tenant isolation proof (insert into `tenant_kebbi.widgets`, confirm 0 rows under `tenant_zamfara`)

Verified without DB (TENANT_NOT_FOUND path, no DB query):
```
GET /api/v1/tenant-info  Header X-Tenant-Id: atlantis  →  404
{
  "success": false,
  "error": { "code": "TENANT_NOT_FOUND", "message": "Unknown tenant: 'atlantis'", "trace_id": "..." },
  "meta": { "trace_id": "..." (matches X-Trace-Id header) }
}
```

**Pending integration verification:** the 5 DB-dependent tests in [test_tenant_context.py](../apps/api/tests/test_tenant_context.py) need migration `0002` applied and the Postgres `postgres` user password set to `devpassword`. Run with `pytest -m integration` once the DB is reachable.

### Step 7 — First real module endpoint: Farmland alerts ✅ **DONE 2026-05-14**

First end-to-end vertical slice: tenant-scoped DB → API → live frontend.

**Backend** ([apps/api/](../apps/api/))
- [`models/alert_event.py`](../apps/api/models/alert_event.py) — 28-column SQLAlchemy mapping. `__table_args__ = {"info": {"is_tenant_scoped": True}}` flags it for Alembic autogenerate to skip (the table lives in per-tenant schemas, not `public`).
- [`migrations/env.py`](../apps/api/migrations/env.py) — added `include_object` filter that excludes tenant-scoped tables from autogenerate.
- [`migrations/versions/0003_create_alert_events.py`](../apps/api/migrations/versions/0003_create_alert_events.py) — drops the placeholder `widgets` and creates `alert_events` in **all 9 pilot schemas**, with:
  - severity/status/alert_type CHECK constraints + confidence_score range check
  - 5 indexes: `(status, created_at DESC)`, `severity`, `alert_type`, `lga`, GIST(`location`)
  - 1 partial index `(created_at DESC) WHERE is_deleted = FALSE` (covers the API's hot path)
  - `updated_at` trigger reusing the function from migration 0001
- [`schemas/farmland.py`](../apps/api/schemas/farmland.py) — `AlertSeverity` / `AlertStatus` / `AlertType` enums, `AlertResponse`, `AlertListData`, `AlertListQuery` (Pydantic-validated query params with `extra="forbid"`).
- [`repositories/alerts.py`](../apps/api/repositories/alerts.py) — composable WHERE-clause builder + 2-query pattern (page + total count, same filters).
- [`services/farmland.py`](../apps/api/services/farmland.py) — business rules (soft-delete filter, default sort) + ORM → Pydantic mapping including PostGIS `POINT` → `{lon, lat}` unwrap via Shapely.
- [`routers/farmland.py`](../apps/api/routers/farmland.py) — `GET /api/v1/farmland/alerts` with full OpenAPI docs, `X-Tenant-Id` requirement (400 if missing), `since` ≤ `until` validation, paginated `SuccessResponse[AlertListData]`.
- [`scripts/seed_farmland_alerts.py`](../apps/api/scripts/seed_farmland_alerts.py) — 9 realistic alerts across Kebbi / Zamfara / Plateau / Kaduna / Benue / Niger with real LGA coordinates, marked `model_name='seed'` for idempotent re-runs.
- [`tests/test_farmland_alerts.py`](../apps/api/tests/test_farmland_alerts.py) — 9 integration tests covering: 400 on missing tenant, 404 on unknown tenant, envelope shape, every required field, pagination, severity filter, status filter, `since>until` validation, and **cross-tenant isolation** (Kebbi alerts never visible to Zamfara queries and vice versa).

**Frontend** ([apps/frontend/](../apps/frontend/))
- Installed `@tanstack/react-query@^5` + devtools.
- [`app/providers.tsx`](../apps/frontend/src/app/providers.tsx) + [`app/layout.tsx`](../apps/frontend/src/app/layout.tsx) — wraps the app in `QueryClientProvider` + `TenantProvider`. QueryClient defaults: 30s `staleTime`, retry once, no refetch-on-window-focus.
- [`lib/api.ts`](../apps/frontend/src/lib/api.ts) — fetch wrapper with `X-Tenant-Id` support, envelope unwrap, `ApiException` class carrying the `error.code` (so React can branch on `TENANT_NOT_FOUND`).
- [`context/TenantContext.tsx`](../apps/frontend/src/context/TenantContext.tsx) — `useTenant()` hook, persists active tenant in `localStorage`, defaults to `kebbi`.
- [`hooks/useFarmlandAlerts.ts`](../apps/frontend/src/hooks/useFarmlandAlerts.ts) — typed TanStack Query hook, multi-value filter support, cancellable via AbortSignal.
- [`components/farmland/FarmlandPanel.tsx`](../apps/frontend/src/components/farmland/FarmlandPanel.tsx) — **rewritten**. Live data drives: the live badge ("LIVE — Kebbi State · N alerts"), the 4 stat tiles (computed from the data), the map pins (filtered to alerts with a location), the alert feed (with loading / error / empty states), the Economic Impact summary. Added a tenant selector + Refresh button.
- [`next.config.ts`](../apps/frontend/next.config.ts) — `connect-src` extended with `http://localhost:8000` so the browser can call the API.

**Verified without DB** (the 400 + 404 paths don't query the DB):
```
GET /api/v1/farmland/alerts                                    → 400 (X-Tenant-Id required)
GET /api/v1/farmland/alerts  X-Tenant-Id: atlantis             → 404 TENANT_NOT_FOUND
GET /api/openapi.json paths                                    → /health, /health/db, /tenant-info, /farmland/alerts
GET http://localhost:3000                                      → 200, dashboard renders
pytest -v                                                       → 6 passed, 16 deselected (@integration)
alembic heads                                                   → 0003 (head)
```

**Pending integration verification** (needs DB password reset + migration):
```
alembic upgrade head                          # applies 0003
python -m scripts.seed_farmland_alerts        # seeds 9 alerts across pilot tenants
pytest -m integration                          # 16 tests (5 tenant_context + 9 farmland_alerts + 2 health_db)
```

Then the frontend `FarmlandPanel` will switch from its "no alerts seeded" empty-state to live data automatically (TanStack Query refetches on tenant change).


- `GET /api/v1/farmland/alerts` returning paginated alerts from `tenant_<id>.farmland_alerts`
- Seed mock alerts in the dev DB
- Replace hardcoded data in [FarmlandPanel.tsx](../apps/frontend/src/components/farmland/FarmlandPanel.tsx) with a TanStack Query call

### Step 8 — Satellite ingestion microservice (Q1)

- Build [apps/ingestion/](../apps/ingestion/) skeleton with Celery + Redis
- One working task: NASA FIRMS daily heat polling for Kebbi ROI
- Write detection results into `tenant_kebbi.heat_signatures`

### Step 9 — Conflict predictor (Q1, port from Citadel)

- Build [apps/ml/](../apps/ml/) FastAPI service exposing `POST /predict/conflict`
- Port Citadel's Random Forest model and SHAP explainer
- Wire it into a nightly cron that writes to `tenant_<id>.conflict_predictions`

### Step 10 — Termii SMS alerts (Q1)

- Termii API key in AWS Secrets Manager
- Background worker dispatches SMS when conflict prediction confidence ≥ 0.75
- Acceptance: end-to-end satellite → DB → SMS in under 30 minutes

### Step 11 — Audit log + DPA tracking (Q1 close-out)

- `AuditLog` middleware writes every mutation
- DPA consent table + UI flow for data subject rights

### Step 12 — Deploy to AWS staging (Q1 finale)

- Terraform: VPC, RDS Multi-AZ, ElastiCache, ECS Fargate, S3, IAM
- GitHub Actions: lint → test → security scan → build → deploy
- Smoke test the Kebbi pilot end-to-end on staging

Anything beyond Step 12 belongs to Q2 and onwards — see [ROADMAP.md](ROADMAP.md).

---

## 6. Known Gotchas / Watch-Outs

- **Build artefacts contain stale strings.** `.next/` under `apps/frontend/` still mentions Bergel/Fellowship because the dev build hasn't been re-run since the cleanup. Run `npm run build` (or just `npm run dev`) and they will be regenerated from the updated source. Optional: `rm -rf apps/frontend/.next`.
- **Next.js version mismatch.** [CLAUDE.md](../CLAUDE.md) says Next.js 14 — `package.json` is pinned to 16.1.7. Either downgrade or update CLAUDE.md when you confirm 16 is intentional.
- **Two source trees.** `economic-bridge-project/` and `economicbridge-new/economicbridge-new-files/` both exist. The former is the active tree; the latter is a partial scaffold. Pick one and delete the other before things diverge further — recommended: keep `economic-bridge-project/`.
- **PgBouncer pool_mode.** Schema-per-tenant requires `pool_mode=session` (not the default `transaction`), or `search_path` resets mid-request. Document this in `infrastructure/pgbouncer/pgbouncer.ini` before deploying.
- **New-geography human review.** [CLAUDE.md §9](../CLAUDE.md) mandates human review for any prediction in a region not previously seen, regardless of confidence. Encode this in the ML service, not the router.
- **AWS region.** Everything must land in `af-south-1` (Cape Town) for NDPA compliance. Don't accidentally deploy to `us-east-1` because Terraform defaults to it.

---

## 7. Handoff Checklist (for a new IDE or agent)

When you (or another AI) pick this up:

- [ ] Read [CLAUDE.md](../CLAUDE.md) in full — non-negotiable conventions
- [ ] Read [ARCHITECTURE.md](ARCHITECTURE.md) — system shape
- [ ] Read this file's § "What's Next" — start at Step 1
- [ ] Run `npm install && npm run dev` in `apps/frontend/` — confirm baseline works
- [ ] Inspect `tenants.yaml` so you know which tenants are `active: true` (start with Kebbi)
- [ ] Check the open ADRs in [docs/decisions/](decisions/) — they bind future decisions
- [ ] Pick up the next undone step in § 5

If you find any drift between this document and the codebase: **the code is the truth**, update this document. If you find drift between [CLAUDE.md](../CLAUDE.md) and the code: **CLAUDE.md is the truth**, fix the code.

---

*Last verified against the codebase on the snapshot date above. Re-verify before relying on it.*
