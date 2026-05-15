# EconomicBridge

**AI & Satellite Mapping for Aid Delivery Optimization**

> A multi-tenant satellite intelligence platform serving NGOs, governments, international bodies, and research institutions across 52 West African administrative units (36 Nigerian states + FCT + 15 ECOWAS countries).

Operated by **Bizra Farms Integrated Nigeria Limited** — *"Using AI to Expand Economic Opportunity"*.

---

## Modules

| # | Module | Description |
|---|--------|-------------|
| 01 | Economic Visibility | Poverty mapping & economic indicators |
| 02 | Aid Coordination | Multi-agency aid delivery optimization |
| 03 | Farmland Protection | Herder-farmer conflict prediction & land monitoring |
| 04 | CropGuard | Crop disease detection & agricultural monitoring |
| 05 | ShockGuard | Flood, drought, and disaster early warning |
| 06 | Economic Mobility Compass | Economic opportunity & mobility insights |
| 07 | SkillsBridge | Skills-to-opportunity matching |

---

## Where to look for what

Everything is split cleanly by service. Frontend code lives in `apps/frontend/`,
backend code lives in `apps/api/` or `apps/ingestion/`. Each service owns its
own configuration, dependencies, virtualenv, and `.env` files.

```
economic-bridge-project/
│
├── apps/
│   ├── frontend/              FRONTEND — Next.js dashboard (port 3000)
│   │   ├── src/                       React/TypeScript components
│   │   ├── package.json               npm dependencies
│   │   ├── next.config.ts             Next.js + CSP headers
│   │   ├── .env.local                 Mapbox token  (gitignored)
│   │   └── .env.local.example         template
│   │
│   ├── api/                   BACKEND API — FastAPI (port 8000)
│   │   ├── main.py                    FastAPI app entrypoint
│   │   ├── config.py                  pydantic-settings
│   │   ├── routers/                   HTTP layer
│   │   ├── services/                  business logic
│   │   ├── repositories/              DB access (no business rules)
│   │   ├── models/                    SQLAlchemy ORM
│   │   ├── schemas/                   Pydantic request/response
│   │   ├── middleware/                Trace, Security, Tenant, Audit
│   │   ├── migrations/                THE active Alembic migrations
│   │   ├── alembic.ini                THE active Alembic config
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   ├── .env                       backend env  (gitignored — create from .env.example)
│   │   └── .env.example               template
│   │
│   └── ingestion/             BACKEND INGESTION — FastAPI (port 8001)
│       ├── main.py                    FastAPI app entrypoint
│       ├── sources/                   external API clients (NASA FIRMS, ...)
│       ├── tasks/                     queue-agnostic ingest tasks
│       ├── routers/                   HTTP layer (health, manual triggers)
│       ├── tests/
│       ├── requirements.txt
│       ├── .env                       NASA FIRMS MAP_KEY etc.  (gitignored)
│       └── .env.example               template
│
├── docs/                      Documentation
│   ├── ARCHITECTURE.md                system shape, data flow, conventions
│   ├── PROGRESS.md                    step-by-step build log
│   ├── ROADMAP.md                     quarterly delivery plan
│   ├── decisions/                     ADRs (ADR-001 schema-per-tenant, ...)
│   └── runbooks/                      operational guides
│
├── infrastructure/            Shared observability
│   ├── prometheus/                    Prometheus config + alert rules
│   └── grafana/                       dashboards + datasource
│
├── scripts/                   Cross-service deployment / tooling
│   ├── deploy.sh                      multi-service deploy
│   ├── generate_tenant.py             tenant provisioning
│   └── validate_tenant.py             tenants.yaml validator
│
├── tenants.yaml               52 tenant configurations (shared by all services)
├── CLAUDE.md                  AI session contract (read before any work)
├── docker-compose.yml         orchestrates all services together
├── Makefile                   high-level make targets
└── README.md                  this file
```

### Config & secrets — at a glance

| File | Who reads it | What's in it |
|------|--------------|--------------|
| `apps/frontend/.env.local`        | Frontend (Next.js)   | `NEXT_PUBLIC_MAPBOX_TOKEN` |
| `apps/api/.env` (create yourself) | Backend API          | `DATABASE_URL`, DB pool tuning |
| `apps/ingestion/.env`             | Backend Ingestion    | `DATABASE_URL`, `NASA_FIRMS_MAP_KEY` |

Every `.env` is **gitignored** by the `.env` rule in `.gitignore`. Templates
live next to them as `.env.example` / `.env.local.example`. **Real secrets
must never leave the gitignored files.** In production, secrets come from
AWS Secrets Manager (see [CLAUDE.md §4.1](CLAUDE.md)).

---

## Quick Start

```powershell
# Frontend (Next.js)
cd apps/frontend
npm install
cp .env.local.example .env.local       # add your Mapbox token
npm run dev                              # http://localhost:3000

# Backend API (FastAPI)
cd apps/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8000

# Backend Ingestion (FastAPI)
cd apps/ingestion
cp .env.example .env                    # add your NASA FIRMS MAP_KEY
& ..\api\.venv\Scripts\python.exe -m uvicorn main:app --port 8001
```

See [docs/PROGRESS.md](docs/PROGRESS.md) for the full step-by-step build log and continuation playbook.

---

## Tech Stack

- **Frontend**: Next.js 16 · React 19 · TypeScript · Mapbox GL · Deck.gl · TanStack Query
- **Backend**: Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Pydantic v2 · Alembic
- **Database**: PostgreSQL 16 · PostGIS · TimescaleDB (optional)
- **Satellite**: Copernicus Sentinel Hub · NASA FIRMS · N2YO · Google Earth Engine
- **ML** (planned): scikit-learn (Random Forest conflict predictor) · PyTorch · SHAP
- **Infra** (planned): AWS ECS Fargate · RDS · S3 · Terraform · GitHub Actions

---

## Multi-Tenancy

Schema-per-tenant PostgreSQL isolation. 52 tenants in `tenants.yaml`. The
active tenant is selected via `X-Tenant-Id` HTTP header; the API's
`TenantContextMiddleware` validates against an allowlist and pins
`SET search_path TO tenant_<id>, public` on the per-request DB session.

See [ADR-001](docs/decisions/ADR-001-tenant-isolation.md) for the design.

---

## Compliance

- **NDPA 2023** (Nigeria Data Protection Act) — full compliance mapping planned
- **Government IT audit** — automated audit package generation (planned)
- **Data sovereignty** — AWS af-south-1 (Cape Town) primary region (planned)

---

## License

Proprietary — Bizra Farms Integrated Nigeria Limited. All rights reserved.
