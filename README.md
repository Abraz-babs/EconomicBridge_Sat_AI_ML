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

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/economicbridge.git
cd economicbridge

# 2. Install dependencies and hooks
make install

# 3. Copy and edit environment variables
cp .env.example .env
# Edit .env with your credentials

# 4. Start development database
make dev-db

# 5. Run migrations
make migrate

# 6. Start all services
make dev
```

## Architecture

```
apps/api/         → FastAPI backend (port 8000)
apps/ingestion/   → Satellite data ingestion microservice (port 8001)
apps/ml/          → ML model serving (port 8002)
apps/frontend/    → Next.js dashboard (port 3000)
infrastructure/   → Terraform (AWS af-south-1) + Kubernetes
migrations/       → Alembic database migrations
scripts/          → Developer & operational tooling
```

## Tech Stack

- **Backend:** Python 3.11 · FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2
- **Frontend:** React 18 · TypeScript · Next.js 14 · Mapbox GL · Deck.gl
- **Database:** PostgreSQL 15 + PostGIS + TimescaleDB · Redis 7
- **Satellite:** Copernicus Sentinel Hub · NASA FIRMS · N2YO · Google Earth Engine
- **ML:** PyTorch 2.0 · Scikit-learn · SHAP · Hugging Face
- **Infra:** AWS ECS Fargate · RDS · S3 · Terraform · GitHub Actions

## Multi-Tenancy

Schema-per-tenant PostgreSQL isolation. 52 tenants configured in `tenants.yaml`. See [ADR-001](docs/decisions/ADR-001-tenant-isolation.md) and [ADR-005](docs/decisions/ADR-005-schema-per-tenant.md).

## Development Commands

Run `make help` to see all available commands. Key targets:

| Command | Description |
|---------|-------------|
| `make dev` | Start full local environment |
| `make test` | Run all tests with coverage |
| `make lint` | Run all linters (ruff, mypy, ESLint) |
| `make security` | Run Bandit, Semgrep, detect-secrets, pip-audit |
| `make migrate` | Run DB migrations for all active tenants |
| `make tenant-provision TENANT=kebbi` | Provision a new tenant |
| `make audit` | Generate government audit package |
| `make deploy-staging` | Deploy to staging (runs all checks first) |

## Compliance

- **NDPA 2023** (Nigeria Data Protection Act) — full compliance mapping
- **Government IT audit** — automated audit package generation
- **Data sovereignty** — AWS af-south-1 (Cape Town) primary region

## Documentation

- `CLAUDE.md` — AI assistant context (read before every session)
- `docs/decisions/` — Architecture Decision Records
- `docs/runbooks/` — Operational runbooks

## License

Proprietary — Bizra Farms Integrated Nigeria Limited. All rights reserved.
