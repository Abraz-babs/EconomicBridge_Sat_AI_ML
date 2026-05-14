# CLAUDE.md — EconomicBridge Platform
# Master context file. Read this fully before every session.
# Last updated: March 2026 | Version: 1.0

---

## 1. PROJECT IDENTITY

**Platform:** EconomicBridge — AI & Satellite Mapping for Aid Delivery Optimization
**Legal Entity:** Bizra Farms Integrated Nigeria Limited (operator of record)
**Mission:** "Using AI to Expand Economic Opportunity"
**Repository:** github.com/[your-username]/economicbridge
**Stage:** Pre-production build (prototype complete, production build starting)

**One-sentence description:**
EconomicBridge is a multi-tenant satellite intelligence platform serving NGOs,
governments, international bodies, and research institutions across 52 West African
administrative units (36 Nigerian states + FCT + 15 ECOWAS countries), providing
actionable economic intelligence across poverty mapping, farmland protection,
agricultural monitoring, and disaster relief.

---

## 2. EXISTING DEPLOYED SYSTEMS (Do not rebuild — inherit patterns from these)

### Sentinel National Intelligence Engine
- Covers all 36 Nigerian states + FCT
- Copernicus Satellite API for imagery capture and interpretation
- N2YO for live satellite pass tracking over Nigeria
- Cybersecurity monitoring: AbuseIPDB + 2 additional threat intelligence APIs
- Monitors critical infrastructure, government, and private sector websites
- OSINT feeds; provisions for SIGINT and IoT scaling
- AI/ML: anomaly detection, NLP on OSINT, LSTM time-series forecasting, ResNet CV

### Citadel Kebbi State Security Dashboard (LIVE AND DEPLOYED)
- NASA FIRMS, Copernicus Sentinel-1 & 2, SAR all-weather, N2YO live pass
- AI/ML: Random Forest conflict prediction, DBSCAN clustering
- Predicts security incidents 24–72 hours in advance
- **This is the reference deployment. All new state deployments mirror this pattern.**

### EconomicBridge Prototype (v0.3 — HTML dashboard)
- Multi-tenant dashboard with role switcher (NGO/Gov/UN-World Bank/Research/Admin)
- Seven modules: Economic Visibility, Aid Coordination, Farmland Protection,
  CropGuard, ShockGuard, Economic Mobility Compass, SkillsBridge
- Farmland Protection module: SAR heat overlay, encroachment alerts, 48-72hr
  conflict prediction timeline, economic impact panel
- **This prototype is the UI/UX specification. Production must match this exactly.**

---

## 3. TECHNICAL STACK (Non-negotiable — do not suggest alternatives)

### Frontend
- React 18 + TypeScript (strict mode — no `any` types anywhere)
- Next.js 14 (App Router)
- Mapbox GL JS for base map rendering
- Deck.gl for satellite layer overlays
- Recharts for data visualisation
- Tailwind CSS for styling
- Zustand for state management
- React Query (TanStack) for server state and caching
- Axios for HTTP client

### Backend
- Python 3.11
- FastAPI (async throughout — no sync endpoints)
- SQLAlchemy 2.0 (async) with Alembic for migrations
- Pydantic v2 for all request/response models
- JWT authentication (python-jose) with refresh tokens
- Kong API Gateway sits in front of FastAPI

### Database
- PostgreSQL 15 with PostGIS extension
- TimescaleDB extension for time-series satellite data
- Schema-per-tenant isolation (CRITICAL — see ADR-001)
- Redis 7 for caching and pub/sub alerts

### Satellite Ingestion (separate microservice)
- Python 3.11 + FastAPI
- Copernicus Sentinel Hub API (imagery)
- NASA FIRMS API (fire/heat)
- N2YO API (live pass tracking)
- Google Earth Engine Python API (preprocessing)
- Celery + Redis for task queue
- Never call satellite APIs from the main application — ingestion only

### AI / ML
- PyTorch 2.0 for deep learning (U-Net flood, ResNet-50 crop disease)
- Scikit-learn for Random Forest conflict prediction (proven in Citadel)
- SHAP for model explainability (required on ALL predictions)
- Hugging Face transformers for NLP
- Claude API for natural language alert summarisation
- Google Earth Engine for satellite preprocessing pipelines

### Infrastructure
- AWS af-south-1 (Cape Town) — primary region (data sovereignty)
- ECS Fargate for containerised services
- RDS PostgreSQL (Multi-AZ)
- ElastiCache Redis
- S3 for satellite imagery (tenant-prefix isolation)
- Terraform for all infrastructure as code
- GitHub Actions for CI/CD
- Docker for all containerisation
- Kubernetes (EKS) for orchestration

### Monitoring
- Prometheus + Grafana for metrics
- AWS CloudWatch for infrastructure logs
- PagerDuty for critical alerts
- Sentry for application error tracking

---

## 4. ARCHITECTURE PRINCIPLES (Enforce these in every file generated)

### 4.1 Security — Non-negotiable rules
- NEVER hardcode secrets, API keys, or credentials anywhere in code
- ALL secrets go through AWS Secrets Manager — accessed via boto3 at runtime
- ALL environment variables defined in .env.example — never in .env committed to git
- ALL database queries use parameterised statements via SQLAlchemy ORM
- NEVER use string concatenation for SQL queries
- JWT tokens expire in 15 minutes (access) and 7 days (refresh)
- ALL endpoints require authentication unless explicitly marked @public
- Rate limiting enforced at Kong gateway level — not in application code
- Input validation on ALL request bodies using Pydantic models
- CORS configured to explicit origin whitelist — never wildcard in production

### 4.2 Multi-tenant isolation (CRITICAL)
- EVERY database query MUST include tenant schema context
- Use the TenantContext middleware — it sets the PostgreSQL search_path
- NEVER query across schemas without bilateral_agreement flag check
- Tenant ID always comes from the JWT token — NEVER from request body
- S3 keys always prefixed with tenant_id — NEVER accept path from client

### 4.3 Code quality standards
- Type hints on ALL functions — no exceptions
- Docstrings on ALL functions and classes (Google style)
- No function longer than 50 lines — extract if exceeded
- No file longer than 300 lines — split if exceeded
- Cyclomatic complexity must stay below 10 per function
- All magic numbers extracted to named constants
- No commented-out code committed to main branch

### 4.4 Error handling
- NEVER use bare `except:` — always catch specific exceptions
- ALL exceptions must be logged with a trace_id
- ALL API errors return structured JSON: {error, message, trace_id, timestamp}
- User-facing error messages must never expose internal details
- Database errors must never be surfaced to API responses

### 4.5 Testing requirements
- Minimum 85% test coverage on all modules (enforced by CI)
- Unit tests for all service functions
- Integration tests for all API endpoints
- Satellite API calls mocked in all tests — never call real APIs in tests
- Database tests use isolated test schemas — never the development database
- Every bug fix must include a regression test

### 4.6 Audit and compliance
- EVERY data-modifying operation writes to the audit log
- Audit log table is INSERT-only — the application user has no DELETE permission
- Audit entries include: tenant_id, user_id, action, resource, timestamp, trace_id, ip_address
- Model inference results logged with: model_version, confidence, input_hash, shap_values
- DPA status checked before serving any PII data

---

## 5. PROJECT STRUCTURE (Always use this — never deviate)

```
economicbridge/
├── CLAUDE.md                    # This file
├── .cursorrules                 # Cursor IDE rules
├── .env.example                 # Environment variable template (no values)
├── .gitignore
├── README.md
├── docker-compose.yml           # Local development
├── docker-compose.test.yml      # Test environment
├── tenants.yaml                 # All 52 tenant configurations
│
├── apps/
│   ├── api/                     # FastAPI backend
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py      # FastAPI dependencies (auth, tenant context)
│   │   ├── middleware/
│   │   │   ├── tenant.py        # TenantContext middleware
│   │   │   ├── audit.py         # AuditLog middleware
│   │   │   └── security.py      # Security headers middleware
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── poverty.py       # Module 01
│   │   │   ├── aid.py           # Module 02
│   │   │   ├── farmland.py      # Module 03
│   │   │   ├── cropguard.py     # Module 04
│   │   │   ├── shockguard.py    # Module 05
│   │   │   ├── mobility.py      # Module 06
│   │   │   ├── skills.py        # Module 07
│   │   │   └── admin.py
│   │   ├── models/              # SQLAlchemy models
│   │   │   ├── base.py          # Base model with audit fields
│   │   │   ├── tenant.py
│   │   │   ├── user.py
│   │   │   ├── alert.py
│   │   │   ├── audit_log.py
│   │   │   └── dpa.py
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic layer
│   │   ├── repositories/        # Database access layer
│   │   └── tests/
│   │
│   ├── ingestion/               # Satellite ingestion microservice
│   │   ├── main.py
│   │   ├── tasks/
│   │   │   ├── copernicus.py
│   │   │   ├── nasa_firms.py
│   │   │   ├── n2yo.py
│   │   │   └── earth_engine.py
│   │   ├── processors/
│   │   │   ├── ndvi.py
│   │   │   ├── sar_flood.py
│   │   │   └── heat_signature.py
│   │   └── tests/
│   │
│   ├── ml/                      # ML model serving microservice
│   │   ├── main.py
│   │   ├── models/
│   │   │   ├── conflict_predictor.py   # Random Forest (Citadel-proven)
│   │   │   ├── flood_detector.py       # U-Net
│   │   │   ├── crop_classifier.py      # ResNet-50
│   │   │   └── poverty_mapper.py       # Gradient Boosted Ensemble
│   │   ├── explainability/
│   │   │   └── shap_explainer.py       # SHAP values for all models
│   │   └── tests/
│   │
│   └── frontend/                # Next.js frontend
│       ├── app/
│       ├── components/
│       │   ├── dashboard/
│       │   ├── map/
│       │   ├── modules/
│       │   │   ├── FarmlandProtection/
│       │   │   ├── CropGuard/
│       │   │   ├── ShockGuard/
│       │   │   └── PovertyMapping/
│       │   └── ui/
│       ├── hooks/
│       ├── stores/
│       ├── types/
│       └── tests/
│
├── infrastructure/
│   ├── terraform/
│   │   ├── main.tf
│   │   ├── rds.tf
│   │   ├── ecs.tf
│   │   ├── s3.tf
│   │   ├── networking.tf
│   │   └── variables.tf
│   └── k8s/
│
├── migrations/                  # Alembic database migrations
│
├── docs/
│   ├── decisions/               # Architecture Decision Records
│   │   ├── ADR-001-tenant-isolation.md
│   │   ├── ADR-002-ingestion-microservice.md
│   │   ├── ADR-003-cape-town-region.md
│   │   ├── ADR-004-fastapi-over-django.md
│   │   └── ADR-005-schema-per-tenant.md
│   ├── api/                     # Auto-generated OpenAPI specs
│   └── runbooks/                # Operational runbooks
│
├── prompts/                     # Versioned AI prompt history
│   └── versions/
│
├── scripts/
│   ├── generate_tenant.py       # Tenant deployment generator
│   ├── validate_tenant.py       # Tenant configuration validator
│   └── audit_package.sh         # Generate government audit package
│
└── audit-package/               # Auto-generated compliance artefacts
    ├── security-scan.json
    ├── coverage-report.html
    ├── dependency-audit.json
    └── compliance-mapping.md
```

---

## 6. DATABASE CONVENTIONS

### Naming
- Tables: snake_case, plural (users, alert_events, tenant_configs)
- Columns: snake_case (created_at, tenant_id, confidence_score)
- Indexes: idx_{table}_{column} (idx_alerts_tenant_id)
- Foreign keys: fk_{table}_{referenced_table} 
- Constraints: chk_{table}_{rule}

### Every table MUST include these base fields
```python
id: UUID (primary key, server default uuid_generate_v4())
tenant_id: UUID (foreign key, NOT NULL — always)
created_at: TIMESTAMPTZ (server default NOW(), NOT NULL)
updated_at: TIMESTAMPTZ (auto-update trigger, NOT NULL)
created_by: UUID (foreign key to users, NOT NULL)
is_deleted: BOOLEAN (default False — soft delete only)
```

### Audit log table (INSERT-only — never UPDATE or DELETE)
```python
id: UUID
tenant_id: UUID
user_id: UUID
action: VARCHAR (CREATE, READ, UPDATE, DELETE, EXPORT, LOGIN, PERMISSION_CHANGE)
resource_type: VARCHAR
resource_id: UUID
old_value: JSONB (nullable)
new_value: JSONB (nullable)
trace_id: UUID
ip_address: INET
user_agent: TEXT
timestamp: TIMESTAMPTZ (server default NOW())
```

---

## 7. API CONVENTIONS

### URL structure
```
/api/v1/{module}/{resource}
/api/v1/farmland/alerts          GET  — list alerts
/api/v1/farmland/alerts/{id}     GET  — single alert
/api/v1/farmland/alerts          POST — create alert
/api/v1/admin/tenants            GET  — admin only
```

### Response envelope (ALL responses use this structure)
```json
{
  "success": true,
  "data": {},
  "meta": {
    "tenant_id": "uuid",
    "trace_id": "uuid",
    "timestamp": "ISO8601",
    "pagination": {}
  },
  "error": null
}
```

### Error response
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Your organisation does not have access to this region.",
    "trace_id": "uuid"
  }
}
```

### HTTP status codes
- 200: Success
- 201: Created
- 400: Validation error (Pydantic)
- 401: Unauthenticated
- 403: Unauthorised (authenticated but no permission)
- 404: Not found
- 422: Unprocessable entity
- 429: Rate limited
- 500: Internal error (never expose details)

---

## 8. SATELLITE DATA SOURCES AND API KEYS

ALL API keys stored in AWS Secrets Manager under these paths:
```
/economicbridge/production/copernicus/client_id
/economicbridge/production/copernicus/client_secret
/economicbridge/production/nasa_firms/api_key
/economicbridge/production/n2yo/api_key
/economicbridge/production/earth_engine/service_account
/economicbridge/production/mapbox/public_token
/economicbridge/production/claude/api_key
/economicbridge/production/termii/api_key
/economicbridge/production/twilio/account_sid
/economicbridge/production/twilio/auth_token
```

Ingestion schedule (driven by N2YO pass events):
- Sentinel-1 SAR: Every 6 days per tenant ROI
- Sentinel-2 MSI: Every 5 days per tenant ROI
- NASA FIRMS: Daily at 06:00 UTC
- VIIRS: Daily at 06:30 UTC
- MODIS: Daily at 07:00 UTC
- N2YO pass check: Every 30 minutes

---

## 9. ML MODEL CONVENTIONS

### Every model inference MUST produce
```python
@dataclass
class ModelPrediction:
    model_name: str
    model_version: str
    tenant_id: UUID
    prediction: float          # 0.0 to 1.0
    confidence: float          # 0.0 to 1.0
    shap_values: dict          # Feature importance
    input_hash: str            # SHA256 of input features
    inference_time_ms: int
    timestamp: datetime
    requires_human_review: bool  # True if new geography or low confidence
```

### Confidence thresholds
- >= 0.90: HIGH — auto-notify agencies
- >= 0.75: MEDIUM — notify with "monitoring" flag
- < 0.75: LOW — log only, require human review before notification
- New geographic area: ALWAYS require human review regardless of confidence

---

## 10. TENANT CONFIGURATION

Tenants defined in tenants.yaml at repo root.
Each tenant has:
```yaml
id: kebbi                        # Unique identifier
name: "Kebbi State"
type: ng_state                   # ng_state | ecowas_country
country: nigeria
capital: "Birnin Kebbi"
language: en                     # en | fr | pt
sms_gateway: termii              # termii | twilio
satellite_roi:                   # Bounding box [min_lon, min_lat, max_lon, max_lat]
  - 3.6
  - 10.8
  - 5.5
  - 13.2
conflict_risk: high              # low | medium | high | critical
priority: 1                      # Deployment phase
deployment_phase: 1
active: true
```

---

## 11. TESTING CONVENTIONS

### Test file naming
- Unit tests: test_{module}_unit.py
- Integration tests: test_{module}_integration.py
- End-to-end tests: test_{flow}_e2e.py

### Test structure (AAA pattern — always)
```python
def test_conflict_predictor_returns_high_confidence_for_known_encroachment():
    # Arrange
    features = ConflictFeatures(heat_signature=0.85, boundary_distance_km=0.5)
    
    # Act
    result = conflict_predictor.predict(features, tenant_id=KEBBI_TENANT_ID)
    
    # Assert
    assert result.confidence >= 0.75
    assert result.shap_values is not None
    assert result.requires_human_review == False
```

### What must always be mocked in tests
- All satellite API calls (Copernicus, NASA, N2YO)
- All external SMS/notification APIs (Termii, Twilio)
- AWS services (use moto library)
- Claude API calls
- Current datetime (use freezegun)

---

## 12. GIT CONVENTIONS

### Branch naming
- feature/{ticket-number}-{short-description}
- fix/{ticket-number}-{short-description}
- hotfix/{ticket-number}-{short-description}
- release/{version}

### Commit message format (Conventional Commits)
```
type(scope): description

feat(farmland): add DBSCAN clustering for herder group detection
fix(auth): resolve JWT refresh token expiry edge case
test(conflict): add regression test for low-confidence threshold
docs(adr): add ADR-006 for alert notification architecture
chore(deps): upgrade SQLAlchemy to 2.0.28
```

Types: feat, fix, test, docs, chore, refactor, perf, security

### PR requirements (CI enforces all of these)
- All tests pass
- Coverage >= 85%
- Bandit security scan: no HIGH or CRITICAL issues
- Semgrep OWASP scan: no findings
- mypy: no type errors
- No merge conflicts
- At least one approval from code owner

---

## 13. WHAT NOT TO DO (Common mistakes to avoid)

- NEVER suggest using Django — FastAPI is the decision (see ADR-004)
- NEVER use synchronous database calls — async throughout
- NEVER put business logic in routers — it goes in services
- NEVER put database queries in services — they go in repositories
- NEVER access tenant data without first setting search_path via TenantContext
- NEVER return raw SQLAlchemy models from API — always serialise via Pydantic schemas
- NEVER log sensitive data (PII, credentials, raw satellite coordinates of individuals)
- NEVER use print() for debugging — use the structured logger
- NEVER create a migration that drops a column — mark as deprecated, remove in next release
- NEVER deploy without running the full audit package generation script

---

## 14. WHEN GENERATING CODE — ALWAYS CHECK

Before generating any code, confirm:
1. Does it include type hints on all functions?
2. Does it include Google-style docstrings?
3. Does it use the TenantContext middleware for database access?
4. Does it write to the audit log for any data modification?
5. Does it use parameterised queries (SQLAlchemy ORM)?
6. Does it handle errors with specific exception types and trace_id logging?
7. Does it mock all external services in its test file?
8. Does it follow the project structure defined in Section 5?
9. Does it follow the API response envelope in Section 7?
10. Are all secrets referenced from AWS Secrets Manager, not environment variables?

If any answer is NO — fix it before presenting the code.

---

*This file is the source of truth for all Claude sessions on this project.*
*If you are unsure about any convention — refer to this file first.*
*If a convention is missing — ask before assuming.*
