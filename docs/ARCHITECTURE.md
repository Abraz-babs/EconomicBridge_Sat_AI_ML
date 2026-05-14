# EconomicBridge — Full Architecture Reference

> Source-of-truth architecture document. Read this first when continuing work in a new IDE or with a new AI agent. Pair this with [CLAUDE.md](../CLAUDE.md) (conventions) and [ROADMAP.md](ROADMAP.md) (delivery timeline).

**Last updated:** 2026-05-11
**Operator:** Bizra Farms Integrated Nigeria Limited
**Stage:** Pre-production (Next.js dashboard live; backend not yet started)

---

## 1. What EconomicBridge Is

A multi-tenant satellite intelligence platform. It serves 52 tenants — 36 Nigerian states + FCT + 15 ECOWAS countries — with seven aid-and-economy modules. The platform turns raw satellite feeds (Sentinel-1, Sentinel-2, NASA FIRMS, VIIRS, MODIS) into agency-ready alerts and dashboards.

The seven modules:

| # | Module | Purpose | Phase |
|---|--------|---------|-------|
| 01 | Economic Visibility | Village-level poverty mapping | Q1 |
| 02 | Aid Coordination Bridge | Multi-tenant aid deduplication | Q1 |
| 03 | **Farmland Protection** | 48–72hr herder-farmer conflict prediction | **Q1 (priority)** |
| 04 | CropGuard | Crop disease detection (14-day early warning) | Q2 |
| 05 | ShockGuard | Flood & drought early warning | Q2 |
| 06 | Economic Mobility Compass | Resettlement & migration planning | Q2 |
| 07 | SkillsBridge | Remote education access mapping | Q3 |

---

## 2. High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    USERS (NGO / Gov / UN / Research)              │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTPS
                              ▼
                ┌──────────────────────────────┐
                │     Next.js 14 Frontend      │   apps/frontend
                │   (Mapbox + Deck.gl + RBAC)  │
                └──────────────┬───────────────┘
                               │ REST + WS
                               ▼
                ┌──────────────────────────────┐
                │      Kong API Gateway        │   rate-limit · auth · CORS
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │     FastAPI Backend          │   apps/api
                │ JWT · TenantContext · Audit  │
                └──┬───────────┬───────────┬───┘
                   │           │           │
       ┌───────────▼┐   ┌──────▼─────┐ ┌──▼──────────────┐
       │  Postgres   │  │   Redis    │ │ ML Service      │
       │  + PostGIS  │  │ cache/pubsub│ │ apps/ml        │
       │  + Timescale│  └─────┬──────┘ └─┬───────────────┘
       │  schema/    │        │           │
       │  tenant     │        │           │
       └──────┬──────┘        │           ▼
              │               │      ┌────────────────┐
              │               │      │ PyTorch · sklearn│
              │               │      │ SHAP explainer  │
              │               │      └────────────────┘
              │               │
              │               ▼
              │      ┌────────────────────────┐
              │      │ Ingestion Service      │   apps/ingestion
              │      │ Celery + Redis queue   │
              │      └─┬──────────────────────┘
              │        │
              │        ├──> Copernicus Sentinel Hub (S1 SAR · S2 MSI)
              │        ├──> NASA FIRMS (fire/heat)
              │        ├──> N2YO (live satellite pass)
              │        └──> Google Earth Engine (preprocessing)
              ▼
       ┌─────────────────────────┐
       │ S3 (af-south-1)         │   tenant-prefixed imagery
       │ Tenant key isolation    │
       └─────────────────────────┘
```

All four apps (`api`, `ingestion`, `ml`, `frontend`) are independent services that scale horizontally on ECS Fargate.

---

## 3. Tech Stack (Non-Negotiable)

### Frontend — `apps/frontend/`
- **Next.js 14** (App Router) — currently on `next@16.1.7` locally
- **React 18 + TypeScript** (strict mode, no `any`)
- **Mapbox GL JS** for base map
- **Deck.gl** for satellite layer overlays
- **Recharts** for charts
- **Tailwind CSS** for styling (planned — currently raw CSS in `globals.css`)
- **Zustand** for client state (planned — currently React Context)
- **TanStack Query** for server state (planned)
- **Axios** as HTTP client

### Backend — `apps/api/`
- **Python 3.11** · **FastAPI** (async only)
- **SQLAlchemy 2.0** async + **Alembic** for migrations
- **Pydantic v2** for all request/response models
- **JWT** via python-jose (15-min access, 7-day refresh)
- **Kong API Gateway** in front

### Database
- **PostgreSQL 15** + **PostGIS** + **TimescaleDB**
- **Schema-per-tenant** isolation (ADR-001) — `tenant_{id}` schemas
- **Redis 7** for cache + pub/sub alerts

### Satellite Ingestion — `apps/ingestion/`
- Python 3.11 + FastAPI + Celery + Redis
- Copernicus Sentinel Hub · NASA FIRMS · N2YO · Google Earth Engine
- **Rule:** main API never calls satellite APIs — ingestion only

### AI / ML — `apps/ml/`
- **PyTorch 2.0** — U-Net (flood), ResNet-50 (crop disease)
- **scikit-learn** — Random Forest conflict predictor (proven in Citadel Kebbi)
- **SHAP** — required on every prediction
- **Hugging Face** transformers for NLP
- **Claude API** for natural-language alert summarisation

### Infrastructure
- **AWS af-south-1 (Cape Town)** — primary, for data sovereignty
- **ECS Fargate** containers
- **RDS Postgres** Multi-AZ
- **ElastiCache Redis**
- **S3** with tenant-prefix isolation
- **Terraform** for IaC
- **GitHub Actions** for CI/CD

### Monitoring
- Prometheus + Grafana (dashboards live in [infrastructure/grafana/](../infrastructure/grafana/))
- AWS CloudWatch + Sentry + PagerDuty

---

## 4. Project Layout

```
economic-bridge-project/
├── CLAUDE.md                  # AI session context (READ FIRST)
├── .cursorrules               # Cursor IDE rules
├── README.md
├── Makefile                   # make dev / make test / make migrate / make audit
├── docker-compose.yml
├── tenants.yaml               # 52 tenant configurations
├── alembic.ini
│
├── apps/
│   ├── frontend/              # Next.js 14 — LIVE (v0.3 dashboard)
│   │   └── src/
│   │       ├── app/           # App Router pages (page.tsx is the dashboard)
│   │       ├── components/    # Header, Footer, SatelliteMap, AlertBar, etc.
│   │       │   ├── farmland/  # FarmlandPanel — Module 03
│   │       │   ├── admin/     # AdminPanel
│   │       │   └── stubs/     # ModuleStub for Q2/Q3 modules
│   │       ├── context/       # RoleContext (RBAC)
│   │       └── data/          # roles.ts — role definitions
│   │
│   ├── api/                   # FastAPI backend — SCAFFOLD ONLY
│   │   ├── core/database.py
│   │   ├── (routers, models, schemas, services, repositories — TBD)
│   │
│   ├── ingestion/             # Satellite microservice — NOT STARTED
│   └── ml/                    # ML serving — NOT STARTED
│
├── infrastructure/
│   ├── grafana/               # dashboards.yml + datasource
│   ├── prometheus/            # prometheus.yml + alert_rules.yml
│   ├── terraform/             # TBD
│   └── k8s/                   # TBD
│
├── migrations/                # Alembic — TBD
│
├── docs/
│   ├── ARCHITECTURE.md        # THIS FILE
│   ├── ROADMAP.md
│   ├── PROGRESS.md            # what's done, what's next, continuation playbook
│   ├── decisions/             # ADR-001 to ADR-005
│   └── runbooks/
│
├── prompts/                   # Versioned AI prompt history
└── scripts/
    ├── generate_tenant.py     # Provision a new tenant (stub)
    ├── validate_tenant.py     # Validate tenants.yaml (stub)
    ├── run_migrations.py      # Multi-tenant Alembic runner (stub)
    ├── init_db.sql            # Extensions + base schema
    └── deploy.sh
```

The split between `economic-bridge-project/` (current working dir) and `economicbridge-new/economicbridge-new-files/` is a historical artefact — `economic-bridge-project/` is the active tree.

---

## 5. Frontend Architecture (LIVE — what's actually built)

The Next.js app at [apps/frontend](../apps/frontend/) is the only currently-running service.

### Entry point — [apps/frontend/src/app/page.tsx](../apps/frontend/src/app/page.tsx)

```
<RoleProvider>
  <ErrorBoundary>
    <DashboardContent>
      <RoleSwitcher />           // Top role chooser
      <Header />                 // Brand + clock + access pill
      <Navigation />             // Tabs: overview, farmland, modules, admin
      <PermissionBanner />       // RBAC notice
      <main>
        {activeTab === 'overview'  && <AlertBar /> + <StatsRow /> + <SatelliteMap /> + ...}
        {activeTab === 'farmland'  && <FarmlandPanel />}            // Module 03 — LIVE
        {activeTab === 'admin'     && currentRole === 'admin' && <AdminPanel />}
        {activeTab === '<other>'   && <ModuleStub />}               // Modules 01/02/04/05/06/07 — stubs
      </main>
      <SystemStatus />
      <Footer />
    </DashboardContent>
  </ErrorBoundary>
</RoleProvider>
```

### Role-Based Access Control

`RoleContext` ([apps/frontend/src/context/RoleContext.tsx](../apps/frontend/src/context/RoleContext.tsx)) drives every component's visibility. Roles defined in [apps/frontend/src/data/roles.ts](../apps/frontend/src/data/roles.ts):

| Role | Label | Access Level |
|------|-------|--------------|
| `ngo` | NGO Partner | Read-only field data |
| `gov` | Government Agency | State-level access |
| `un` | UN / World Bank | Multi-tenant aggregated view |
| `research` | Research Institution | Anonymised research view |
| `admin` | Platform Admin | Full access, AdminPanel visible |

### Overview tab composition

- **AlertBar** — rotating priority alerts
- **StatsRow** — 4 KPI tiles
- **SatelliteMap** — placeholder for Mapbox/Deck.gl integration (currently styled div)
- **IntelligenceFeed** — chronological intelligence events
- **DataAccessMatrix** — RBAC matrix visualisation
- **CoverageTrend** / **CropHealthIndex** / **ActiveResponse** — chart placeholders

### Module 03 — Farmland Protection

The flagship module. [apps/frontend/src/components/farmland/FarmlandPanel.tsx](../apps/frontend/src/components/farmland/FarmlandPanel.tsx) renders the SAR heat overlay, encroachment alerts, and 48–72hr conflict prediction timeline that the architecture promises. Backed by mocked data today — will wire to `/api/v1/farmland/alerts` when backend lands.

---

## 6. Backend Architecture (PLANNED — scaffold only)

The FastAPI service follows a strict layered architecture defined in [CLAUDE.md §5](../CLAUDE.md). One golden rule: **routers → services → repositories → database**. Cross-layer calls are not allowed.

### Layer responsibilities

| Layer | Lives in | Allowed to | Forbidden |
|-------|----------|------------|-----------|
| Router | `apps/api/routers/` | Parse request, call service, format response | DB access, business logic |
| Service | `apps/api/services/` | Business logic, orchestrate repositories | Direct SQL, HTTP responses |
| Repository | `apps/api/repositories/` | Database queries via SQLAlchemy | HTTP, business decisions |
| Model | `apps/api/models/` | SQLAlchemy ORM definitions | Logic, queries |
| Schema | `apps/api/schemas/` | Pydantic request/response validation | DB access |

### Middleware stack (request order)

1. **SecurityHeaders** — strict-transport, CSP, X-Frame-Options
2. **Auth** — verify JWT, attach `user` and `tenant_id` to request state
3. **TenantContext** — `SET search_path = tenant_{id}` on DB connection
4. **AuditLog** — capture every mutating request to audit table
5. **TraceId** — inject trace_id into logger context for the request

### Standard response envelope

```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "tenant_id": "uuid",
    "trace_id": "uuid",
    "timestamp": "2026-05-11T12:34:56Z",
    "pagination": {}
  },
  "error": null
}
```

Error envelope mirrors the same shape with `success: false` and a structured `error` block. HTTP codes follow [CLAUDE.md §7](../CLAUDE.md).

---

## 7. Multi-Tenant Isolation

See [ADR-001](decisions/ADR-001-tenant-isolation.md) for the full decision record.

**Schema-per-tenant, single RDS instance.** Each tenant gets `tenant_{id}` (e.g. `tenant_kebbi`, `tenant_ghana`). A `tenant_shared` schema holds read-only reference data accessible to all.

### Enforcement points

1. **JWT carries `tenant_id`** — never trust request body for tenant identity
2. **TenantContext middleware** sets `search_path` per connection
3. **PgBouncer** runs in `pool_mode=session` so search_path persists
4. **S3 keys** prefixed `s3://eb-imagery/{tenant_id}/...` — verified server-side
5. **Cross-schema queries** structurally impossible except via `bilateral_agreement` flag path

### Provisioning a new tenant

```bash
# 1. Add tenant block to tenants.yaml
# 2. Validate config
python scripts/validate_tenant.py --tenant-id <id>
# 3. Generate schema + IAM + S3 prefix
python scripts/generate_tenant.py --tenant-id <id>
# 4. Run migrations against the new schema
make migrate TENANT=<id>
```

---

## 8. Data Model — Base Conventions

Every business table inherits these fields (defined in `apps/api/models/base.py`):

```python
id          UUID            # server default uuid_generate_v4()
tenant_id   UUID NOT NULL   # always present, FK to tenant registry
created_at  TIMESTAMPTZ     # server default NOW()
updated_at  TIMESTAMPTZ     # auto-update trigger
created_by  UUID NOT NULL   # FK to users
is_deleted  BOOLEAN         # soft delete only — never hard delete
```

### Audit log — append only

The `audit_log` table is **INSERT-only**. The application database user has no UPDATE or DELETE grant on this table. Captured per write:

```
id · tenant_id · user_id · action · resource_type · resource_id
old_value (JSONB) · new_value (JSONB)
trace_id · ip_address · user_agent · timestamp
```

Actions: `CREATE | READ | UPDATE | DELETE | EXPORT | LOGIN | PERMISSION_CHANGE`.

---

## 9. Satellite Data Sources & Cadence

| Source | API | Cadence | Used by |
|--------|-----|---------|---------|
| Sentinel-1 SAR | Copernicus | Every 6 days per ROI | ShockGuard (flood), Farmland (boundary) |
| Sentinel-2 MSI | Copernicus | Every 5 days per ROI | CropGuard (NDVI), Poverty Mapping |
| NASA FIRMS | NASA | Daily 06:00 UTC | Farmland (heat), ShockGuard (fire) |
| VIIRS | NASA | Daily 06:30 UTC | Poverty Mapping (nightlight) |
| MODIS | NASA | Daily 07:00 UTC | ShockGuard (drought, thermal) |
| N2YO live pass | N2YO | Every 30 min | Ingestion orchestrator |

All API keys live in **AWS Secrets Manager** under `/economicbridge/production/<source>/<key>`. Never in `.env` files.

---

## 10. ML Convention

Every model inference produces a `ModelPrediction` dataclass (see [CLAUDE.md §9](../CLAUDE.md)):

```
model_name · model_version · tenant_id
prediction (0.0–1.0) · confidence (0.0–1.0)
shap_values (dict) · input_hash (SHA256)
inference_time_ms · timestamp
requires_human_review (bool)
```

### Confidence routing

| Confidence | Action |
|------------|--------|
| ≥ 0.90 | Auto-notify agencies |
| ≥ 0.75 | Notify with "monitoring" flag |
| < 0.75 | Log only, require human review |
| New geography | Always require human review regardless |

### Trained models (planned)

- `conflict_predictor.py` — Random Forest (Kebbi-proven). Inputs: heat_signature, boundary_distance_km, NDVI delta, historical incidents. Outputs: 48–72hr conflict probability.
- `flood_detector.py` — U-Net on Sentinel-1 SAR. Works through cloud cover.
- `crop_classifier.py` — ResNet-50 on Sentinel-2 NDVI patches.
- `poverty_mapper.py` — Gradient Boosted Ensemble on VIIRS nightlight + building footprints.

---

## 11. Security & Compliance Posture

### Non-negotiable (enforced in CI)

- No hardcoded secrets — AWS Secrets Manager only
- All endpoints authenticated unless `@public`
- Parametrised queries only — no string concatenation
- Bandit + Semgrep + detect-secrets + pip-audit on every PR
- 85%+ test coverage gate
- Pydantic validation on every request body

### NDPA 2023 (Nigeria Data Protection Act)

- Tenant data residency: AWS af-south-1 (Cape Town)
- DPA tracking table — consent state per data subject
- Right-to-erasure via soft-delete + nightly purge job
- Government IT audit: schema isolation visually verifiable + automated audit package via `make audit`

### Trust boundaries

| Boundary | Control |
|----------|---------|
| Client → API | JWT + Kong rate limiting + CORS allowlist |
| API → DB | Per-tenant search_path, RDS in private subnet |
| API → Ingestion | Internal mTLS + signed messages |
| Ingestion → Satellite APIs | Egress-only, secrets from Secrets Manager |
| API → ML | Internal HTTP, ML never sees raw PII |

---

## 12. Deployment Model

```
GitHub Actions
  ├─ lint (ruff · mypy · eslint)
  ├─ test (pytest · vitest) — coverage gate at 85%
  ├─ security (bandit · semgrep · detect-secrets · pip-audit)
  ├─ build docker images
  ├─ push to ECR
  └─ deploy to ECS Fargate (staging → manual approval → production)
```

Environments:

| Env | AWS Region | Branch | DB |
|-----|-----------|--------|----|
| dev (local) | n/a | feature/* | docker-compose postgres |
| staging | af-south-1 | develop | RDS Multi-AZ small |
| production | af-south-1 | main | RDS Multi-AZ + read replica |

---

## 13. Architecture Decision Records

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-001](decisions/ADR-001-tenant-isolation.md) | Schema-per-tenant isolation | Accepted |
| ADR-002 | Ingestion as separate microservice | Pending write-up |
| ADR-003 | AWS Cape Town as primary region | Pending write-up |
| ADR-004 | FastAPI over Django | Pending write-up |
| ADR-005 | Schema-per-tenant (detail addendum) | Pending write-up |

---

## 14. How to Continue This Project in a New IDE

1. Open `economic-bridge-project/` as your workspace root
2. Read [CLAUDE.md](../CLAUDE.md) end-to-end — it is the source of truth for conventions
3. Read [PROGRESS.md](PROGRESS.md) for current state and the prioritised next-step list
4. Run the frontend locally to confirm baseline:
   ```bash
   cd apps/frontend
   npm install
   npm run dev
   # http://localhost:3000
   ```
5. Pick the next ticket from `PROGRESS.md` § "What's Next"

---

*If something in this document conflicts with the code, the code is wrong and this document is right — fix the code. If something conflicts with [CLAUDE.md](../CLAUDE.md), CLAUDE.md wins because it carries the AI session contract.*
