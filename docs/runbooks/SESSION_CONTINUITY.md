# Session Continuity & Handoff — read this first

**Purpose:** let a fresh assistant session (even on a new computer) pick up the
project from a known state — including how to use our AWS CLI and other accesses.

> ⚠️ **This file contains NO secrets.** Credentials (AWS keys, API keys,
> passwords) live only in the gitignored root `.env` and in AWS Secrets Manager.
> This doc tells you *where* they are and *how* to wire them, never their values.
> The public repo is `github.com/Abraz-babs/EconomicBridge_Sat_AI_ML`.

---

## 0. The 30-second picture

- **Product:** EconomicBridge — multi-tenant satellite-intelligence platform
  (operator: Bizra Farms Integrated Nigeria Ltd). 7 modules, 10 live pilot
  tenants. See `CLAUDE.md` for the full spec.
- **Where work happens:** `economic-bridge-project/` (NOT `economicbridge-new/`).
- **Status (2026-06-30):** the "genuineness program" is **complete** — every
  satellite-fed map module is live, per-LGA, multi-sensor, with a provenance
  panel. Details in §6.
- **Staging is LIVE on AWS** at the ALB below; deploy + migrations are scripted.

---

## 1. AWS access (CLI + console)

- **Account:** `198566079411` · **Region:** `eu-west-1` · **Profile:** `economicbridge`
- **IAM user:** `economicbridge-deployer` (has AdministratorAccess + access keys).
- **Console:** `https://198566079411.signin.aws.amazon.com/console`
  (user `economicbridge-deployer`, authenticator-app MFA `Abdullah-A04`).
- **ROOT is locked out** (Nigerian-carrier SMS MFA won't deliver). Day-to-day is
  fully usable via the deployer IAM admin login. ROOT is only needed for Billing
  (the $60 credit / plan upgrade) — Support case open.

**Setting it up on a NEW machine:**
```sh
aws configure --profile economicbridge   # paste the deployer's access key + secret
# region eu-west-1
```
The access keys are held by the operator and can be regenerated in the IAM
console (Users → economicbridge-deployer → Security credentials). Once the
profile exists, every command below works with `AWS_PROFILE=economicbridge`.

**Note for Git Bash on Windows:** prefix log/ARN commands with
`MSYS_NO_PATHCONV=1` so leading-slash args (e.g. `/ecs/...` log groups) aren't
rewritten into Windows paths.

---

## 2. Live infrastructure

- **ALB (staging URL):** `http://economicbridge-staging-alb-691775567.eu-west-1.elb.amazonaws.com`
- **ECS cluster:** `economicbridge-staging-cluster`
- **Services:** `economicbridge-staging-{api,ingestion,ml,notifications,frontend}`
- **Routing:** one ALB origin; backends are prefix-routed —
  `/api/v1` (api), `/ingestion/api/v1`, `/ml/api/v1`, `/notifications/api/v1`.
- **Budget mode is ON** (NAT dropped → tasks run in PUBLIC subnets + public IP;
  notifications right-sized; `ml` left running). Rollback runbook:
  `infrastructure/terraform/BUDGET_MODE.md`.

Discover the live network config (subnets/SG) for run-task instead of hardcoding:
```sh
AWS_PROFILE=economicbridge aws ecs describe-services \
  --cluster economicbridge-staging-cluster --services economicbridge-staging-api \
  --query 'services[0].networkConfiguration.awsvpcConfiguration'
```

---

## 3. Deploy (GitHub Actions, manual)

- Workflow: **Deploy** (`.github/workflows/deploy.yml`), `workflow_dispatch`.
  Inputs: environment (staging/production), services (`all` or comma list),
  image_tag (default = commit SHA).
- It builds per-service images (context = `apps/<svc>`), pushes to ECR via the
  OIDC role `github-actions-deploy`, then `ecs update-service --force-new-deployment`.
- **Base images come from ECR Public** (`public.ecr.aws/docker/library/...`) to
  dodge Docker Hub's anonymous rate limit — keep it that way.
- The operator triggers deploys from the GitHub UI; the assistant cannot.
  Standard loop: commit + push to `main` → tell the operator which services to
  deploy → verify live via the ALB.

---

## 4. One-shot ECS tasks (migrations, sweeps, DB ops)

RDS is private — reach it by launching a throwaway Fargate task that reuses a
service task definition with a command override. This is the supported pattern.

**Migrations** (after a deploy that adds one):
```sh
make ecs-migrate ENV=staging          # or: scripts/ecs_migrate.sh staging
```
This runs `alembic upgrade head` inside the VPC. Needs the deployer creds.

**Arbitrary task** (full sweeps, DB queries, cleanups) — the generic recipe:
```sh
export AWS_PROFILE=economicbridge AWS_REGION=eu-west-1 MSYS_NO_PATHCONV=1
CLUSTER=economicbridge-staging-cluster
B64=$(python -c "import base64;print(base64.b64encode(b'<python here>').decode())")
NET='awsvpcConfiguration={subnets=[<from describe-services>],securityGroups=[<sg>],assignPublicIp=ENABLED}'
OVR=$(printf '{"containerOverrides":[{"name":"ingestion","command":["sh","-c","cd /app && python -c \\"import base64;exec(base64.b64decode(%s))\\""]}]}' "'$B64'")
aws ecs run-task --cluster $CLUSTER --task-definition economicbridge-staging-ingestion \
  --launch-type FARGATE --platform-version LATEST \
  --network-configuration "$NET" --overrides "$OVR" --started-by ad-hoc \
  --query 'tasks[0].taskArn' --output text
# then: aws ecs wait tasks-stopped ...; read logs from /ecs/economicbridge-staging/<svc>
```
Use `economicbridge-staging-api` for DB/migrations, `-ingestion` for sweeps.
Examples used in practice: full encroachment/shockguard seed sweeps
(`run_<x>_sweep(full=True)`), seed soft-deletes, live DB diagnostics.

---

## 5. The live feeds (scheduler) — "nothing silent"

In-process APScheduler in the **ingestion** service (`apps/ingestion/scheduler.py`),
running 11 jobs. Confirm + introspect:
```
GET  /ingestion/api/v1/scheduler/jobs            # running? + next_run_time per job
POST /ingestion/api/v1/scheduler/jobs/{id}/run   # fire any job now (Admin → Scheduler)
GET  /ingestion/api/v1/scheduler/runs/recent     # last runs (only 3 sources stamp this)
```
Cadence: pass-imagery (15m); FIRMS/conflict/encroachment(+VIIRS new-light)/
ShockGuard (daily); satellite-obs/WorldPop/poverty-VIIRS (weekly);
mobility/aid/skills (monthly). `recs=0` on FIRMS/conflict/shock is honest
quiet (no fires/conflicts/shocks), not a fault.

---

## 6. Genuineness program — what is REAL now

| Module | Live satellite data |
|---|---|
| Farmland | S1 SAR + S2 NDVI + FIRMS + VIIRS new-light, **per-LGA, all states** |
| Economic Visibility (poverty) | real **VIIRS Black Marble** radiance + WorldPop |
| CropGuard | trained ResNet-50 + live CDSE Farm Check (S2/S1) |
| ShockGuard | **per-LGA** S1/S2 flood+drought (live + labelled historical) |
| Mobility / Skills / Aid | World Bank / UNICEF GIGA / OCHA HAPI |

Key facts: Farmland encroachment + ShockGuard are revisit-matched rolling
per-LGA sweeps; the CDSE client has 429 backoff; VIIRS is read as true per-pixel
HDF5 radiance (`apps/ingestion/sources/viirs_raster.py`). Provenance:
`GET /api/v1/provenance` → ProvenancePanel on the Overview tab.

---

## 7. Banked / deferred work (itemised)

**Gated on the operator / external:**
1. **NASRDA gateway** — create org (all 10 pilots, all modules) + login. HOLD
   until NASRDA approves and provides the email + password (do not create uninvited).
2. **HTTPS + custom domain** — currently HTTP only; add domain + ACM cert.
3. **Email (Resend)** — needs a verified domain; then populate the secret +
   set `email_backend=resend` + redeploy api. (SES was abandoned.)
4. **SMS** — AWS SNS path wired; needs SNS sandbox exit + Nigeria sender-ID (NCC).
5. **AWS ROOT recovery** — for Billing / the $60 credit / plan upgrade.
6. **Plan upgrade before credits hit $0**; then roll back budget mode (BUDGET_MODE.md).

**Optional code (lower value):**
7. Real **WorldPop population** in poverty (still a hash proxy; the headline
   radiance is already real).
8. **Live PU-meter** — capture the `x-processingunits-spent` CDSE header.
9. **ingestion_runs stamping for all feeds** (only 3 stamp it today) → full
   "last ran" observability.
10. **"Locate" 📍 button** on coordinate cards; **MODIS LST** for live drought;
    test-coverage climb; GEE/Planet Labs (Phase B providers).

---

## 8. Local dev + gotchas

- Services + ports: frontend 3001, api 8000, ingestion 8001, ml 8002,
  notifications 8003. `make dev` (docker-compose) or per-service `make dev-<svc>`.
- **Python env split:** api/ingestion/notifications use `apps/api/.venv`
  (shapely/rasterio/h5py); ML + crop training use the global Python (torch).
  Wrong env → request-time 500.
- Local Postgres on `localhost:5434`; `DATABASE_URL` in root `.env`.
- Never run `next build` while `next dev` is running (freezes HMR). On restart,
  kill ALL uvicorn child PIDs (reloader children survive parent kill).
- CI fresh-resolves unpinned fastapi/starlette; reproduce CI-only failures in a
  throwaway venv.

---

## 9. Pointers / source of truth

- `CLAUDE.md` — master spec & conventions (read fully each session).
- `docs/ARCHITECTURE.md`, `docs/PROGRESS.md` — architecture + narrative.
- `docs/runbooks/operations.md` — ops runbook; `.github/workflows/README.md` —
  CI/deploy notes.
- `docs/partnerships/EconomicBridge_DG_Briefing.{md,pdf}` — the DG presentation.
- **Assistant session memory** lives at
  `~/.claude/projects/<project>/memory/` on the *original* machine and does NOT
  travel between computers — **this doc + the git repo are the portable handoff.**
  On a new machine, start from `CLAUDE.md` + this file.
