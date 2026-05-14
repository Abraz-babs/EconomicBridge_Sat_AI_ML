# EconomicBridge — Makefile
# All developer commands in one place.
# Usage: make <command>
# Run `make help` to see all available commands.

.DEFAULT_GOAL := help
.PHONY: help install dev test lint security migrate tenant audit clean

# ─────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────

help: ## Show this help message
	@echo ""
	@echo "EconomicBridge — Developer Commands"
	@echo "═══════════════════════════════════════════════════════"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────

install: ## Install all dependencies (first-time setup)
	@echo "→ Installing Python dependencies..."
	cd apps/api && pip install -r requirements.txt -r requirements-dev.txt
	cd apps/ingestion && pip install -r requirements.txt -r requirements-dev.txt
	cd apps/ml && pip install -r requirements.txt -r requirements-dev.txt
	@echo "→ Installing Node dependencies..."
	cd apps/frontend && npm install
	@echo "→ Installing pre-commit hooks..."
	pre-commit install
	@echo "→ Copying .env.example to .env (if not exists)..."
	cp -n .env.example .env || true
	@echo "✓ Setup complete. Edit .env before running."

install-tools: ## Install required system tools (run once on new machine)
	pip install pre-commit bandit semgrep mypy pytest coverage
	npm install -g @commitlint/cli @commitlint/config-conventional

# ─────────────────────────────────────────────────────────────────
# DEVELOPMENT
# ─────────────────────────────────────────────────────────────────

dev: ## Start full local development environment (all services)
	docker-compose up --build

dev-api: ## Start only the API service
	cd apps/api && uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-ingestion: ## Start only the ingestion service
	cd apps/ingestion && uvicorn main:app --reload --host 0.0.0.0 --port 8001

dev-ml: ## Start only the ML service
	cd apps/ml && uvicorn main:app --reload --host 0.0.0.0 --port 8002

dev-worker: ## Start Celery worker for ingestion tasks
	cd apps/ingestion && celery -A tasks worker --loglevel=info --concurrency=4

dev-frontend: ## Start Next.js development server
	cd apps/frontend && npm run dev

dev-db: ## Start only PostgreSQL and Redis (useful for backend-only development)
	docker-compose up postgres redis

# ─────────────────────────────────────────────────────────────────
# TESTING
# ─────────────────────────────────────────────────────────────────

test: ## Run all tests with coverage report
	@echo "→ Running API tests..."
	cd apps/api && pytest tests/ --cov=. --cov-report=html --cov-fail-under=85 -v
	@echo "→ Running ingestion tests..."
	cd apps/ingestion && pytest tests/ --cov=. --cov-report=html --cov-fail-under=85 -v
	@echo "→ Running ML tests..."
	cd apps/ml && pytest tests/ --cov=. --cov-report=html --cov-fail-under=85 -v
	@echo "→ Running frontend tests..."
	cd apps/frontend && npm test -- --coverage

test-api: ## Run only API tests
	cd apps/api && pytest tests/ -v --cov=. --cov-report=term-missing

test-integration: ## Run integration tests (requires running database)
	cd apps/api && pytest tests/ -v -m integration

test-unit: ## Run unit tests only (no external dependencies)
	cd apps/api && pytest tests/ -v -m unit

test-watch: ## Run tests in watch mode (re-runs on file change)
	cd apps/api && pytest tests/ -v --watch

coverage-report: ## Open HTML coverage report in browser
	open apps/api/htmlcov/index.html

# ─────────────────────────────────────────────────────────────────
# CODE QUALITY
# ─────────────────────────────────────────────────────────────────

lint: ## Run all linters
	@echo "→ Running ruff (Python linter)..."
	ruff check apps/api apps/ingestion apps/ml
	@echo "→ Running mypy (type checker)..."
	mypy apps/api apps/ingestion apps/ml --strict
	@echo "→ Running ESLint (TypeScript)..."
	cd apps/frontend && npm run lint
	@echo "✓ All linters passed."

lint-fix: ## Auto-fix linting issues where possible
	ruff check apps/ --fix
	cd apps/frontend && npm run lint -- --fix

format: ## Format all code
	ruff format apps/api apps/ingestion apps/ml
	cd apps/frontend && npx prettier --write .

format-check: ## Check formatting without modifying files
	ruff format apps/ --check
	cd apps/frontend && npx prettier --check .

typecheck: ## Run type checking only
	mypy apps/api apps/ingestion apps/ml --strict

# ─────────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────────

security: ## Run all security scans
	@echo "→ Running Bandit (Python security)..."
	bandit -r apps/api apps/ingestion apps/ml -ll -f json -o audit-package/bandit-report.json
	bandit -r apps/api apps/ingestion apps/ml -ll
	@echo "→ Running Semgrep (OWASP rules)..."
	semgrep --config p/owasp-top-ten --config p/python apps/api apps/ingestion apps/ml
	@echo "→ Checking for secrets in codebase..."
	detect-secrets scan --baseline .secrets.baseline
	@echo "→ Auditing Python dependencies..."
	pip-audit --format json -o audit-package/dependency-audit.json
	pip-audit
	@echo "✓ Security scan complete. Check audit-package/ for reports."

security-watch: ## Continuously run security checks on file changes
	watchmedo shell-command --patterns="*.py" --recursive \
		--command='bandit -r apps/ -ll' apps/

check-secrets: ## Scan for accidentally committed secrets
	detect-secrets scan

# ─────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────

migrate: ## Run database migrations for all active tenants
	@echo "→ Running migrations for all active tenants..."
	python scripts/run_migrations.py --all-tenants

migrate-tenant: ## Run migrations for a specific tenant (usage: make migrate-tenant TENANT=kebbi)
	@echo "→ Running migrations for tenant: $(TENANT)..."
	python scripts/run_migrations.py --tenant-id $(TENANT)

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add alert table")
	cd apps/api && alembic revision --autogenerate -m "$(MSG)"

migrate-rollback: ## Rollback last migration for all tenants
	python scripts/run_migrations.py --all-tenants --downgrade -1

db-shell: ## Open PostgreSQL shell
	docker-compose exec postgres psql -U economicbridge -d economicbridge

db-reset: ## Reset development database (DESTRUCTIVE — dev only)
	@echo "⚠️  WARNING: This will destroy all development data."
	@read -p "Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	docker-compose down postgres
	docker volume rm economicbridge_postgres_data || true
	docker-compose up -d postgres
	sleep 3
	make migrate

# ─────────────────────────────────────────────────────────────────
# TENANT MANAGEMENT
# ─────────────────────────────────────────────────────────────────

tenant-provision: ## Provision a new tenant (usage: make tenant-provision TENANT=kebbi)
	@echo "→ Provisioning tenant: $(TENANT)..."
	python scripts/generate_tenant.py --tenant-id $(TENANT)
	python scripts/validate_tenant.py --tenant-id $(TENANT)
	make migrate-tenant TENANT=$(TENANT)
	@echo "✓ Tenant $(TENANT) provisioned successfully."

tenant-validate: ## Validate tenant configuration (usage: make tenant-validate TENANT=kebbi)
	python scripts/validate_tenant.py --tenant-id $(TENANT)

tenant-list: ## List all configured tenants and their status
	python scripts/list_tenants.py

tenant-deactivate: ## Deactivate a tenant (usage: make tenant-deactivate TENANT=kebbi)
	python scripts/manage_tenant.py --tenant-id $(TENANT) --action deactivate

# ─────────────────────────────────────────────────────────────────
# SATELLITE / INGESTION
# ─────────────────────────────────────────────────────────────────

ingest-test: ## Run test ingestion with synthetic data (no real API calls)
	cd apps/ingestion && python -m tasks.test_ingestion --synthetic

ingest-firms: ## Manually trigger NASA FIRMS ingestion for all active tenants
	cd apps/ingestion && celery -A tasks call tasks.nasa_firms.ingest_all_tenants

ingest-status: ## Check ingestion queue status
	cd apps/ingestion && celery -A tasks inspect active

# ─────────────────────────────────────────────────────────────────
# COMPLIANCE & AUDIT
# ─────────────────────────────────────────────────────────────────

audit: ## Generate complete government audit package
	@echo "→ Generating audit package..."
	bash scripts/audit_package.sh
	@echo "✓ Audit package generated in audit-package/"
	@ls -la audit-package/

audit-open: ## Open audit package directory
	open audit-package/

compliance-check: ## Run NDPA 2023 compliance checks
	python scripts/compliance_check.py --framework ndpa2023

# ─────────────────────────────────────────────────────────────────
# DEPLOYMENT
# ─────────────────────────────────────────────────────────────────

deploy-staging: ## Deploy to staging environment
	@echo "→ Running pre-deployment checks..."
	make lint
	make test
	make security
	@echo "→ Deploying to staging..."
	./scripts/deploy.sh staging

deploy-production: ## Deploy to production (requires all checks to pass)
	@echo "⚠️  PRODUCTION DEPLOYMENT"
	@echo "→ Running all pre-deployment checks..."
	make lint
	make test
	make security
	make audit
	@echo "→ All checks passed. Deploying to production..."
	./scripts/deploy.sh production

# ─────────────────────────────────────────────────────────────────
# INFRASTRUCTURE
# ─────────────────────────────────────────────────────────────────

infra-plan: ## Preview Terraform infrastructure changes
	cd infrastructure/terraform && terraform plan

infra-apply: ## Apply Terraform infrastructure changes
	cd infrastructure/terraform && terraform apply

infra-destroy: ## Destroy Terraform infrastructure (DESTRUCTIVE)
	@echo "⚠️  WARNING: This will destroy all cloud infrastructure."
	@read -p "Type 'destroy' to continue: " confirm && [ "$$confirm" = "destroy" ]
	cd infrastructure/terraform && terraform destroy

# ─────────────────────────────────────────────────────────────────
# PROMPTS (Versioned AI prompt management)
# ─────────────────────────────────────────────────────────────────

prompt-save: ## Save current prompt to version history (usage: make prompt-save DESC="add conflict model")
	python scripts/save_prompt.py --description "$(DESC)"

prompt-list: ## List all saved prompt versions
	python scripts/list_prompts.py

prompt-diff: ## Show diff between two prompt versions (usage: make prompt-diff V1=001 V2=002)
	python scripts/diff_prompts.py --v1 $(V1) --v2 $(V2)

# ─────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────

clean: ## Remove all build artifacts, caches, and temporary files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	cd apps/frontend && rm -rf .next node_modules/.cache 2>/dev/null || true
	@echo "✓ Cleaned."

logs: ## Tail all service logs
	docker-compose logs -f

logs-api: ## Tail API logs only
	docker-compose logs -f api

logs-ingestion: ## Tail ingestion service logs
	docker-compose logs -f ingestion

health: ## Check health of all running services
	curl -s http://localhost:8000/health | python -m json.tool
	curl -s http://localhost:8001/health | python -m json.tool
	curl -s http://localhost:8002/health | python -m json.tool

version: ## Show current version
	@cat apps/api/VERSION

bump-version: ## Bump version (usage: make bump-version TYPE=patch|minor|major)
	python scripts/bump_version.py --type $(TYPE)
