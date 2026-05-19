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

### Step 8 — Satellite ingestion microservice (Q1) ✅ **DONE 2026-05-14**

Second microservice landed: a separate FastAPI app at port 8001 that pulls
satellite data from external sources and writes it to the tenant schemas.

**Queue deferred:** Celery + Redis would be the standard backbone here, but no
Docker / Redis on this machine. The tasks are written as queue-agnostic async
functions, with a manual trigger router for now. When Redis lands the function
body in `tasks/firms_ingest.py` does not change — only the caller does.

Delivered:
- [migrations/versions/0004_create_heat_signatures.py](../apps/api/migrations/versions/0004_create_heat_signatures.py) — `public.ingestion_runs` (audit of every ingestion job) + `tenant_<id>.heat_signatures` across all 9 pilot schemas with GIST + time-range indexes
- [apps/ingestion/](../apps/ingestion/) — separate FastAPI service:
  - [config.py](../apps/ingestion/config.py) — pydantic-settings with optional `NASA_FIRMS_MAP_KEY`
  - [db.py](../apps/ingestion/db.py) — its own async engine + `set_tenant_schema()` helper (the ingestion service writes across multiple tenants in one run, so `search_path` is set per-tenant per-task, not per-request)
  - [sources/nasa_firms.py](../apps/ingestion/sources/nasa_firms.py) — typed FIRMS REST client with CSV parser. **Mock fallback** when no MAP_KEY is configured: returns 3 deterministic detections anchored to the bbox centre so the rest of the pipeline (parser → schema → DB writer → audit log) is exercisable in dev without registering for an API key. Bounding boxes mirror tenants.yaml for the 9 pilot tenants
  - [tasks/firms_ingest.py](../apps/ingestion/tasks/firms_ingest.py) — `ingest_firms_for_tenant()`. Lifecycle: INSERT `ingestion_runs` row (status=running) → fetch detections → INSERT into `tenant_<id>.heat_signatures` → UPDATE run row (succeeded / failed + duration_ms + records_ingested). Supports `dry_run=True` (no detection writes; counts what would be inserted). Identifier-safe `SET search_path` via the allowlist
  - [routers/health.py](../apps/ingestion/routers/health.py) — `GET /api/v1/health` reports `nasa_firms_configured` so operators can see when the real API is wired
  - [routers/triggers.py](../apps/ingestion/routers/triggers.py) — `POST /api/v1/ingest/firms` with Pydantic body validation (`tenant_id`, optional `source`, `day_range` 1..10, `dry_run`). Returns the full IngestResult: run_id, status, records_ingested, duration_ms
  - [main.py](../apps/ingestion/main.py) — FastAPI app with `TraceIdMiddleware` (X-Trace-Id header) + CORS; docs at `/api/docs`
  - [tests/](../apps/ingestion/tests/) — 12 tests total. 8 unit (CSV parser corner cases, mock client, /health) + 4 integration (full DB round-trip including a dry-run check and an unknown-tenant 404)
- [.env.example](../apps/ingestion/.env.example) + [requirements.txt](../apps/ingestion/requirements.txt) + [pytest.ini](../apps/ingestion/pytest.ini)

Verified without DB:
```
pytest -v                                            8 passed, 4 deselected (@integration)
GET  /api/v1/health                                  200 {nasa_firms_configured: false}
GET  /api/openapi.json paths                         /health, /ingest/firms
POST /api/v1/ingest/firms {tenant_id:"atlantis"}     404 Unknown tenant
```

**Pending DB integration verification** (needs `alembic upgrade head` + Postgres password reset):
```powershell
cd apps/api
.\.venv\Scripts\python.exe -m alembic upgrade head
cd ../ingestion
& ..\api\.venv\Scripts\python.exe -m pytest -m integration
# → 4 ingest tests + the 21 from api side = 25 integration tests covering
#   tenant context, alerts, and now FIRMS ingestion end-to-end
```

**To run the service:**
```powershell
cd apps/ingestion
& ..\api\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
# Swagger: http://localhost:8001/api/docs
```

**Pivot to Celery (the "Step 8.1" follow-up when Redis is available):**
1. `pip install celery[redis]` (already commented into requirements.txt)
2. Wrap `ingest_firms_for_tenant` in `@celery_app.task` — the body is unchanged
3. Add `celery beat` schedule: daily 06:00 UTC for every active tenant
4. Make `POST /ingest/firms` call `.delay()` and return 202 with the AsyncResult id



### Step 9 — Conflict predictor (Q1, port from Citadel) ✅ **DONE 2026-05-15**

Third microservice landed: ML inference at port 8002. Random Forest +
SHAP explainability, per-tenant persistence, full CLAUDE.md §9 contract.

Delivered:
- [migrations/versions/0005_create_conflict_predictions.py](../apps/api/migrations/versions/0005_create_conflict_predictions.py) — per-tenant `conflict_predictions` table across all 9 pilot schemas. Captures the full ModelPrediction contract (model_version, prediction, confidence, confidence_band, requires_human_review, features JSONB, shap_values JSONB, input_hash, location, trace_id). 5 indexes including a partial index on `requires_human_review = TRUE` for the operator review queue.
- [apps/ml/](../apps/ml/) — fourth FastAPI service:
  - [config.py](../apps/ml/config.py) — pydantic-settings reading the project-root `.env`
  - [db.py](../apps/ml/db.py) — own async engine + `set_tenant_schema()` helper with allowlist guard
  - [models/prediction.py](../apps/ml/models/prediction.py) — `ModelPrediction` dataclass + `band_for_confidence()`. CLAUDE.md §9 thresholds (HIGH ≥ 0.90, MEDIUM ≥ 0.75) live in one place. Self-consistency check rejects mismatched band vs confidence
  - [models/conflict_predictor.py](../apps/ml/models/conflict_predictor.py) — `ConflictFeatures` dataclass + `ConflictPredictor` class. Lazy-loaded singleton. **On first call** with no artifact on disk, trains a Random Forest (160 trees, max_depth=12) from a synthetic-but-domain-grounded dataset (4096 samples, logit constructed from heat × distance × NDVI × herder × history × rainfall) and persists to `apps/ml/artifacts/conflict_predictor.joblib`. SHAP `TreeExplainer` baked into the artifact. Handles both 2-D and 3-D SHAP return shapes (old vs new SHAP versions). `is_new_geography=True` ALWAYS forces human review, regardless of confidence (CLAUDE.md §9)
  - [schemas/conflict.py](../apps/ml/schemas/conflict.py) — `ConflictPredictionRequest` (7 features + optional location + `persist` flag) and `ConflictPredictionData` (prediction + SHAP + audit fields)
  - [schemas/envelope.py](../apps/ml/schemas/envelope.py) — same response envelope as the other services
  - [routers/health.py](../apps/ml/routers/health.py) — `GET /api/v1/health`
  - [routers/predict.py](../apps/ml/routers/predict.py) — `POST /api/v1/predict/conflict`. Pydantic validates feature ranges (heat ∈ [0,1], rainfall ∈ [-1,1], etc.). On `persist=True`, INSERT into `tenant_<id>.conflict_predictions` with the GIST-indexed location, JSONB features + SHAP, FK to optional `related_alert_id`
  - [main.py](../apps/ml/main.py) — FastAPI app with `TraceIdMiddleware` + CORS
  - [tests/](../apps/ml/tests/) — 22 tests total. **21 unit pass** (model contract + RF predictor behaviour: high-risk → positive prediction, low-risk → negative, new geography → review forced, SHAP one entry per feature) + **1 DB integration** (persist round-trip)

Verified without DB:
```
pytest -v                                          21 passed, 1 deselected (71.92s)
GET  /api/v1/health                                200 {ok, ml service}
POST /api/v1/predict/conflict (high-risk Kebbi)    200
  prediction:        0.9834
  confidence_band:   HIGH
  requires_review:   false
  inference_ms:      62
  Top SHAP feature:  boundary_distance_km (+0.151)
```

Now four services running locally side-by-side:
```
Frontend     http://localhost:3000   (Next.js)
API          http://localhost:8000   (FastAPI: health, tenant-info, farmland/alerts)
Ingestion    http://localhost:8001   (FastAPI: health, ingest/firms)
ML           http://localhost:8002   (FastAPI: health, predict/conflict)
```

**Pending integration verification** (needs DB password reset + `alembic upgrade head`):
```powershell
cd apps/ml
& ..\api\.venv\Scripts\python.exe -m pytest -m integration
# → 1 persistence round-trip test
```

**Future iterations** (out of Step 9 scope):
- Conflict predictor v1 trained on Citadel's real labelled set (replaces the synthetic-data artifact)
- U-Net flood detector (Step 10's neighbour)
- ResNet-50 crop disease classifier
- Cron driver that feeds heat_signatures + alert_events into the predictor on a daily beat (Celery beat once Redis lands)

### Step 10 — Termii SMS alerts (Q1) ✅ **DONE 2026-05-15**

Fifth microservice landed: `apps/notifications` at port 8003. SMS dispatch
pipeline with Termii (Nigerian carriers) + Twilio (ECOWAS) + a MockGateway
that lets dev runs go end-to-end without external API keys.

Delivered:
- [apps/api/migrations/versions/0006_create_sms_outbox_and_subscribers.py](../apps/api/migrations/versions/0006_create_sms_outbox_and_subscribers.py)
  — two tables:
  - `public.sms_outbox` — cross-tenant audit of every dispatch, INSERT-only
    with a controlled UPDATE RULE that allows status / provider_message_id
    / cost fields to advance (sent → delivered) while immutable fields are
    pinned (CLAUDE.md §4.6 + outbox pattern)
  - `tenant_<id>.alert_subscribers` — per-tenant subscriber rosters with
    E.164 phone validation, severity threshold, alert-type opt-in, language,
    spatial location, consent timestamps (NDPA-grade)
  - UNIQUE (prediction_id, subscriber_id) partial index = idempotency
    guarantee: the same prediction never goes to the same subscriber twice
- [apps/notifications/](../apps/notifications/) — service layout:
  - [config.py](../apps/notifications/config.py) — pydantic-settings; reads
    root `.env`; exposes `termii_configured` / `twilio_configured`
  - [db.py](../apps/notifications/db.py) — async engine + allowlist-checked
    `set_tenant_schema()`
  - [gateways/base.py](../apps/notifications/gateways/base.py) — `SmsGateway`
    Protocol + `SendResult` dataclass (one shape for all providers)
  - [gateways/mock.py](../apps/notifications/gateways/mock.py) — logs SMS to
    stdout, returns `status='mock'`. Used automatically when the
    tenant's primary provider isn't configured
  - [gateways/termii.py](../apps/notifications/gateways/termii.py) — Termii
    REST client (api_key-in-body quirk handled). Parses response → SendResult
  - [gateways/twilio.py](../apps/notifications/gateways/twilio.py) — Twilio
    Messages REST (form-encoded body, HTTP Basic auth)
  - [schemas/notify.py](../apps/notifications/schemas/notify.py) — closed-set
    enums (Severity, AlertType, Language, Channel, SeverityThreshold) that
    mirror the DB CHECK constraints
  - [services/providers.py](../apps/notifications/services/providers.py) —
    pilot tenant → gateway map from tenants.yaml (NG→termii, ECOWAS→twilio)
    with mock fallback when keys are missing
  - [services/messages.py](../apps/notifications/services/messages.py) —
    SMS template renderer + subscriber-preference matcher (`should_dispatch`)
  - [services/dispatcher.py](../apps/notifications/services/dispatcher.py) —
    orchestrator: fetch matching subscribers → INSERT outbox row →
    call gateway → UPDATE outbox row with result. Commits after every
    step so a network failure mid-batch never loses the audit trail
  - [routers/](../apps/notifications/routers/) — `GET /health`,
    `GET/POST /api/v1/subscribers` (per-tenant CRUD via X-Tenant-Id),
    `POST /api/v1/notify/conflict`
  - [tests/](../apps/notifications/tests/) — 36 tests total (8 message
    templates + 6 provider selection + 7 gateway parsers + 2 health +
    9 router + 1 integration). Unit tests run without any external
    dependency

Verified without DB:
```
/health                                          200 {ok, termii=false, twilio=false}
/api/openapi.json paths                          /health, /subscribers, /notify/conflict
POST /notify/conflict {tenant=atlantis}          404 Unknown tenant
POST /notify/conflict {severity=catastrophic}    422 enum validation
```

Now **five services** running locally side-by-side:
```
Frontend       :3000   (Next.js dashboard)
API            :8000   (FastAPI: health, tenant-info, farmland/alerts)
Ingestion      :8001   (FastAPI: NASA FIRMS, real data flowing)
ML             :8002   (FastAPI: Random Forest + SHAP conflict predictor)
Notifications  :8003   (FastAPI: SMS dispatch, Termii + Twilio + mock)
```

**Pending DB verification + real keys** (independent of Step 10 code):
- `alembic upgrade head` (now lands 0001–0006) once Postgres password reset
- Register for a Termii API key + add to `.env` → real SMS to Nigerian numbers
- Register for Twilio + add to `.env` → real SMS to Ghana/Senegal

**Step 10.1** (next iteration, when Redis + Celery land):
- ML service auto-fires POST to /notify/conflict on every HIGH-band prediction
- A worker scans `public.sms_outbox` for `status='failed'` and retries with backoff

### Step 10.5 — Live SMS dispatch verified end-to-end ✅ **DONE 2026-05-18**

Mid-step session that proved the full SMS chain works against a live Postgres
+ live Termii account. Found and fixed two bugs that blocked dispatch:

- **Migration 0007** ([apps/api/migrations/versions/0007_fix_sms_outbox_immutability.py](../apps/api/migrations/versions/0007_fix_sms_outbox_immutability.py))
  — replaced the recursive `ON UPDATE DO INSTEAD UPDATE` rule on `sms_outbox`
  (which 500'd with `infinite recursion detected in rules`) with a BEFORE
  UPDATE trigger that raises if any identity/content column changed. The
  lifecycle columns (status, provider_message_id, dispatched_at, cost) now
  advance cleanly.
- **Termii sender ID quirk** — `EconoBridge` and the assumed-reserved
  `N-Alert` both 404'd as `ApplicationSenderId not found`. Termii accounts
  start with **zero registered senders**; one must be requested via the
  portal (24-72hr approval). Submitted `Ecobridge` for transactional/alert
  use-case; awaiting approval. Pipeline otherwise reaches Termii's API,
  captures the failure into `public.sms_outbox`, completes audit cycle.

The 10th pilot tenant — **Nasarawa State** — also landed in this same
session per field-team feedback (Tiv-Fulani herder-farmer flashpoint):

- [Migration 0008](../apps/api/migrations/versions/0008_add_nasarawa_tenant.py)
  creates `tenant_nasarawa` schema + 4 per-tenant tables
- [Migration 0009](../apps/api/migrations/versions/0009_align_nasarawa_alert_events.py)
  adds 7 columns the original 0008 omitted (`boundary`, `model_input_hash`,
  `shap_values`, `reviewed_by`, `reviewed_at`, `reviewer_notes`, `created_by`)
  so the schema matches what 0003 ships for the original 9 pilots
- Tenant added to allowlists in 4 places: `apps/api/services/tenants.py`,
  `apps/notifications/db.py`, `apps/notifications/services/providers.py`,
  `apps/frontend/src/context/TenantContext.tsx`
- Seed extended with 3 Nasarawa alerts (Awe critical / Doma high acknowledged
  / Lafia medium resolved) plus 2 each for FCT, Ghana, Senegal — total
  18 alerts across 10 tenants

Farmland Protection dashboard also reached production-grade interactivity
in this session:
- `PATCH /api/v1/farmland/alerts/{id}` endpoint — lifecycle transitions
  (resolved / acknowledged / dismissed / pending_review)
- Frontend resolve flow: "Mark resolved" + "Acknowledge" buttons on every
  alert card, optimistic mutation via TanStack Query
- Tenant-aware satellite metadata overlay (no more frozen "Coverage: NW Nigeria")
- Hover tooltips on map pins with lat/lon to 4 decimal places + full alert detail
- Pulsing critical/high pins (sine-wave radius modulation via Deck.gl)
- HEAT / NDVI / SAR / BOUNDARIES layer toggles now visually distinct
  (orange heatmap / green vegetation grid / blue radar / ROI polygon)
- Map auto-flies to active tenant centroid on switch
- Lat/lon displayed on every alert item
- Timeline + economic impact panels now derived from live alerts
  (4 priority groups, dynamic footnote listing real satellite_source strings,
  mean confidence, agencies engaged)

Frontend dependency fix: API venv was missing `shapely` — GeoAlchemy2 needs
it to convert PostGIS POINT → lon/lat. Added to `apps/api/requirements.txt`
so Docker images install it correctly.

### Step 11 — Audit log + DPA tracking (Q1 close-out) ✅ **DONE 2026-05-18**

The audit middleware stub was replaced with a real `INSERT` into
`public.audit_log` for every POST / PUT / PATCH / DELETE. CLAUDE.md §4.6
is now actually enforced rather than aspirational.

Delivered:
- [middleware/audit.py](../apps/api/middleware/audit.py) — real INSERT
  middleware. Captures `trace_id`, `tenant_schema`, `action_type`,
  `http_method`, `path`, `status_code`, `ip_address`, `data_type`, severity.
  Wraps `call_next` in `try/except` so unhandled-5xx exceptions also write
  a synthetic-500 audit row before re-raising. Fail-soft: an audit-insert
  error logs to stderr but never breaks the customer response.
- [Migration 0010](../apps/api/migrations/versions/0010_create_dpa_and_dsr.py)
  creates two new `public` tables:
  - `data_processing_agreements` — one row per Organisation × Tenant scope
    with `status ∈ {pending, signed, expired, revoked}`, `signed_at`,
    `expires_at`, `scope` (JSONB list), `document_url`. Partial index on
    `(organisation_id, tenant_id) WHERE status='signed'` for the hot-path
    "is this org allowed in this tenant?" lookup.
  - `data_subject_requests` — NDPA-2023 / GDPR right-of-subject tracker
    with `request_type ∈ {access, rectification, erasure, portability,
    objection}`. CHECK constraint requires either `subject_phone_e164` or
    `subject_email` so we can't track an anonymous request.
- ORM + Pydantic + 7 endpoints in [routers/dpa.py](../apps/api/routers/dpa.py):
  POST/GET/PATCH for DPAs, POST/GET/PATCH for DSRs
- Two bugs found and fixed during smoke test:
  1. DPA model omitted `DateTime(timezone=True)` → asyncpg refused to encode
     tz-aware `datetime.now(timezone.utc)`. Explicit `DateTime(timezone=True)`
     added to all 6 datetime columns.
  2. Audit middleware initially missed exception-derived 500s because
     Starlette re-raises through middleware in debug mode. Wrapped `call_next`
     in `try/except` that writes a synthetic-500 row and re-raises.

Smoke test trail in `public.audit_log`:
```
POST   /api/v1/dpa/agreements              → 201  CREATE_DPA_AGREEMENT
PATCH  /api/v1/dpa/agreements/{id}         → 200  UPDATE_DPA_AGREEMENT
POST   /api/v1/dpa/data-subject-requests   → 201  CREATE_DSR (erasure)
PATCH  /api/v1/dpa/data-subject-requests/{id} → 200  UPDATE_DSR
PATCH  /api/v1/farmland/alerts/{id}        → 200  UPDATE_ALERT (×2)
```

**Open from Step 11:** the actual DPA *enforcement* layer (block PII access
without a signed DPA) is not yet wired into the request path. Tables exist,
endpoints work, partial index ready — the gate dependency lands in Step 13.

### Step 12 — Deploy to AWS staging (Q1 finale)

#### Step 12a — Containerization ✅ **DONE 2026-05-18**

Every service is now Dockerized with a 2-stage (3 for frontend) production
build, and a single `docker compose up --build` brings up the whole stack.

Delivered:
- [apps/api/Dockerfile](../apps/api/Dockerfile) — multi-stage with libgeos +
  libpq, non-root user, /health curl healthcheck
- [apps/ingestion/Dockerfile](../apps/ingestion/Dockerfile) — same pattern,
  port 8001
- [apps/ml/Dockerfile](../apps/ml/Dockerfile) — adds OpenBLAS / LAPACK
  runtime libs for sklearn; mounts the `eb-ml-artifacts` named volume so
  the Random Forest model persists across restarts
- [apps/notifications/Dockerfile](../apps/notifications/Dockerfile) — same
  pattern, port 8003
- [apps/frontend/Dockerfile](../apps/frontend/Dockerfile) — 3-stage Next.js
  (deps → builder → runner using `output: 'standalone'`); `NEXT_PUBLIC_*`
  baked at build time via `--build-arg`
- [.dockerignore](../.dockerignore) — excludes secrets, venvs, node_modules,
  `.next`, tests, model artifacts, the 99MB PostGIS installer
- [docker-compose.yml](../docker-compose.yml) — postgres+postgis 16, redis 7,
  one-shot `migrate` service running `alembic upgrade head`, and the 5
  application services with healthchecks + dependency conditions. Future
  scaffolding (Celery, Flower, Prometheus, Grafana) preserved as commented
  blocks for Step 10.1 and observability rollout.
- [.env.docker.example](../.env.docker.example) — the 2 compose-only vars
  (DB_PASSWORD override, NEXT_PUBLIC_* for the frontend build) + pointer
  to the existing root `.env` for everything else

Two source files edited to support the build:
- [next.config.ts](../apps/frontend/next.config.ts) — added `output: "standalone"`
- [requirements.txt](../apps/api/requirements.txt) — added `shapely>=2.0,<3.0`

#### Step 12b — Terraform IaC ✅ **DONE 2026-05-19**

Full production layout shipped. 20 files, ~70 AWS resources. Staging
targets `eu-west-1` (Ireland) for cost (~$60-100/mo) with production
overrides queued for `af-south-1` (Cape Town).

Delivered ([infrastructure/terraform/](../infrastructure/terraform/)):
- [versions.tf](../infrastructure/terraform/versions.tf), [backend.tf](../infrastructure/terraform/backend.tf),
  [providers.tf](../infrastructure/terraform/providers.tf) — Terraform 1.9+,
  AWS provider ~> 5.70, S3 backend at
  `economicbridge-tf-state-198566079411` with DynamoDB locking,
  workspace-namespaced state keys
- [variables.tf](../infrastructure/terraform/variables.tf),
  [locals.tf](../infrastructure/terraform/locals.tf),
  [data.tf](../infrastructure/terraform/data.tf) — all input variables
  (staging-optimised defaults), `services` map driving every `for_each`,
  `secret_paths` matching CLAUDE.md §8
- [network.tf](../infrastructure/terraform/network.tf) — VPC `10.40.0.0/16`,
  2 AZs, public + private subnets, IGW + NAT (single for staging,
  per-AZ for prod), S3 gateway endpoint to dodge NAT egress costs
- [security_groups.tf](../infrastructure/terraform/security_groups.tf) — ALB
  (443/80 from internet), ECS tasks (per-service port from ALB), RDS
  (5432 from ECS only), Redis (6379 from ECS only) — strict
  defence-in-depth
- [ecr.tf](../infrastructure/terraform/ecr.tf) — 5 repos, IMMUTABLE tags,
  scan-on-push, lifecycle (keep 20 tagged, expire untagged after 7d)
- [secrets.tf](../infrastructure/terraform/secrets.tf) — RDS password
  (Terraform-generated, 32 chars) + 10 external-provider secrets created
  empty with `PLACEHOLDER_NOT_SET`, `lifecycle.ignore_changes` so the
  operator's `aws secretsmanager put-secret-value` doesn't fight Terraform
- [iam.tf](../infrastructure/terraform/iam.tf) — shared ECS execution role +
  one task role per service (least-privilege), RDS enhanced-monitoring role
- [rds.tf](../infrastructure/terraform/rds.tf) — PostgreSQL 16.4 Multi-AZ,
  gp3 storage with autoscaling 20→100GB, encrypted at rest, `rds.force_ssl`,
  enhanced monitoring + Performance Insights, deletion-protection toggle
- [redis.tf](../infrastructure/terraform/redis.tf) — Redis 7.1 replication
  group, at-rest + in-transit encryption, automatic failover when
  `redis_num_cache_nodes >= 2`
- [alb.tf](../infrastructure/terraform/alb.tf) — ALB, 5 target groups, HTTPS
  listener (TLS-1.3 policy) when ACM cert provided else HTTP-only, path-based
  routing (`/api/v1/*` → api, `/ingestion/*` → ingestion, etc., `/*` →
  frontend)
- [logs.tf](../infrastructure/terraform/logs.tf) — 1 CloudWatch log group
  per service, 14d retention staging / 90d prod
- [ecs.tf](../infrastructure/terraform/ecs.tf) — Fargate cluster + 5
  task definitions + 5 services with `awsvpc` networking, container insights
  enabled, CPU target-tracking autoscaling, deployment circuit breaker with
  auto-rollback, secrets injected via Secrets Manager
- [alarms.tf](../infrastructure/terraform/alarms.tf) — SNS topic + alarms
  on ALB 5xx, ECS CPU per service, RDS CPU + storage, Redis CPU
- [outputs.tf](../infrastructure/terraform/outputs.tf) — ALB DNS, RDS
  endpoint, ECR URLs, secret ARNs, log groups
- [terraform.tfvars.example](../infrastructure/terraform/terraform.tfvars.example),
  [README.md](../infrastructure/terraform/README.md) — operator runbook
  for first-time deploy, secret population, image push, prod promotion

Resource count ≈ 80. First `terraform apply` ≈ 25 minutes (RDS is the
long tail). Operator runs `terraform init` + `apply` after installing
Terraform 1.9+ and configuring `aws configure`.

#### Step 12c — GitHub Actions (queued)

- CI workflow: lint + ruff + mypy + pytest + bandit + semgrep on every PR
- CD workflow: manual-trigger build → push to ECR → update ECS services
- No GitHub-hosted runners needed beyond ubuntu-latest

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
