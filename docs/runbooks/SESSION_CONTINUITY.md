# Session Continuity & Handoff — read this first

**Purpose:** let a fresh assistant session (even on a new computer, even a
different model) pick up the project from a known state — including how to use
our AWS CLI, GitHub push, deploy automation, and one-shot compute.

> ⚠️ **This file contains NO secrets.** Credentials (AWS keys, API keys,
> passwords, tokens) live only in the gitignored root `.env`, in AWS Secrets
> Manager, and in the OS credential store. This doc tells you *where* they are
> and *how* to wire them, never their values.
> The public repo is `github.com/Abraz-babs/EconomicBridge_Sat_AI_ML`.

**Last updated:** 2026-09-04

---

## 0. The 30-second picture

- **Product:** EconomicBridge — multi-tenant satellite-intelligence platform
  (operator: Bizra Farms Integrated Nigeria Ltd). 7 modules, 10 pilot tenants,
  447 LGAs. See `CLAUDE.md` for the full spec.
- **Where work happens:** `economic-bridge-project/` (NOT `economicbridge-new/`).
- **Live at** `https://economicbridge.org` (HTTPS, custom domain, Resend email).
- **You can push and deploy yourself.** See §3 — an earlier version of this doc
  said the assistant could not. That was wrong and cost a session's worth of
  false blockers.
- **Newest module:** the **storm engine** (half-hourly IMERG). Built 2026-09-02,
  deployed 2026-09-04. It is a MEASUREMENT feed, not an alerting product — §6.

---

## 1. AWS access (CLI + console)

- **Account:** `198566079411` · **Region:** `eu-west-1` · **Profile:** `economicbridge`
- **IAM user:** `economicbridge-deployer` (AdministratorAccess + access keys).
- **Console:** `https://198566079411.signin.aws.amazon.com/console`
- **ROOT was recovered 2026-07-20** (an earlier version of this doc said it was
  locked out — no longer true). Console MFA restored.

**Setting up on a NEW machine:**
```sh
aws configure --profile economicbridge   # deployer access key + secret; region eu-west-1
```

**Git Bash on Windows:** prefix commands whose args start with `/` with
`MSYS_NO_PATHCONV=1`, or `/ecs/...` log-group names get rewritten into Windows
paths and the call fails with a confusing validation error.

---

## 2. Live infrastructure

- **Public URL:** `https://economicbridge.org` (ACM cert; old ALB links reroute)
- **ALB:** `economicbridge-staging-alb-691775567.eu-west-1.elb.amazonaws.com`
- **ECS cluster:** `economicbridge-staging-cluster`
- **Services:** `economicbridge-staging-{api,ingestion,ml,notifications,frontend}`
- **Routing:** one ALB origin, prefix-routed — `/api/v1` (api),
  `/ingestion/api/v1`, `/ml/api/v1`, `/notifications/api/v1`.
- **Budget mode is ON** (no NAT → tasks run in PUBLIC subnets with a public IP).
  Rollback: `infrastructure/terraform/BUDGET_MODE.md`.
- **Terraform has `ignore_changes = [task_definition]`.** Deploys do NOT bump the
  task-definition revision — `api:8` and `ingestion:5` stay put while the image
  behind the tag changes. **Verify a deploy by task `startedAt` / image digest,
  never by revision number.**

---

## 3. Push + deploy — YOU CAN DO BOTH FROM THE SESSION

This section exists because it was wrong for months and blocked real work.

### 3a. Git push (Windows / Git Credential Manager)

The GitHub PAT **is** stored in Windows Credential Manager, but under
**username-qualified** targets:

```
LegacyGeneric:target=git:https://github.com
LegacyGeneric:target=git:https://Abraz-babs@github.com
```

A bare remote URL makes git look up `host=github.com` with **no username**,
which misses the stored entry — GCM then tries to prompt, and in a
non-interactive session that surfaces as:

```
fatal: could not read Username for 'https://github.com'
```

**That is a lookup miss, not a missing credential.** Do not conclude the push is
blocked. The remote is now permanently set to the username-qualified form, so a
plain push works:

```sh
git push origin main       # remote is https://Abraz-babs@github.com/Abraz-babs/...
```

If it ever regresses:
```sh
git remote set-url origin https://Abraz-babs@github.com/Abraz-babs/EconomicBridge_Sat_AI_ML.git
```

**Never set `GIT_TERMINAL_PROMPT=0` while diagnosing** — it turns a fixable
lookup miss into a hard "prompts disabled" error that reads like no credential.

To confirm the credential exists without printing it:
```powershell
$inp = "protocol=https`nhost=github.com`nusername=Abraz-babs`n`n"
($inp | & "C:\Program Files\Git\mingw64\bin\git-credential-manager.exe" get) |
  ForEach-Object { if ($_ -match '^password=(.*)$') { "password=<{0} chars>" -f $matches[1].Length } else { $_ } }
```
`git-credential-manager` is NOT on PATH; it lives at
`C:\Program Files\Git\mingw64\bin\git-credential-manager.exe`.

### 3b. Triggering a deploy (no `gh` CLI installed)

Deploy is `workflow_dispatch` on `.github/workflows/deploy.yml`. Dispatch it via
the REST API using the same PAT — retrieve into a variable, never print it:

```powershell
$inp = "protocol=https`nhost=github.com`nusername=Abraz-babs`n`n"
$tok = (($inp | & "C:\Program Files\Git\mingw64\bin\git-credential-manager.exe" get) |
         Where-Object { $_ -match '^password=' }) -replace '^password=', ''
$hdr  = @{ Authorization = "Bearer $tok"; Accept = "application/vnd.github+json"; "User-Agent" = "eb-deploy" }
$body = @{ ref = "main"; inputs = @{ environment = "staging"; services = "all" } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Headers $hdr `
  -Uri "https://api.github.com/repos/Abraz-babs/EconomicBridge_Sat_AI_ML/actions/workflows/deploy.yml/dispatches" `
  -ContentType "application/json" -Body $body      # 204 = accepted
```

`services` accepts `all` or a comma list (`api,frontend`). Deploy only what
changed — a frontend-only fix does not need the ingestion image rebuilt.

**Watch the run** (`per_page=4` covers CI + Deploy for the last two SHAs):
```powershell
Invoke-RestMethod -Headers $hdr -Uri "https://api.github.com/repos/Abraz-babs/EconomicBridge_Sat_AI_ML/actions/runs?per_page=4"
```
The run-level `status` can read `queued` while matrix jobs are already
succeeding — check `/actions/runs/<id>/jobs` for the truth.

CI runs automatically on push and is credential-free. Deploy authenticates to
AWS via OIDC (`github-actions-deploy`); there are no AWS keys in GitHub.

### 3c. Migrations are NOT run by the deploy

```sh
make ecs-migrate ENV=staging          # or scripts/ecs_migrate.sh staging
```
Run it AFTER the deploy that ships the image containing the migration.

---

## 4. One-shot compute (DB queries, sweeps, backfills)

RDS is private. Reach it with a throwaway Fargate task reusing a service task
definition with a command override. **Three gotchas, all of which cost real time:**

1. **The security group is REQUIRED.** Omit it and the task gets the VPC default
   SG, RDS refuses, and you get a bare `asyncio.CancelledError` with no hint.
2. **Set `PYTHONPATH=/app`.** A script executed from `/tmp` puts `/tmp` on
   `sys.path`, not the cwd → `ModuleNotFoundError: No module named 'db'`.
   `/app` itself is **not writable** by the container user, so write to `/tmp`
   and set PYTHONPATH rather than writing into `/app`.
3. **Log streams are `ingestion/ingestion/<task-id>`** (not `ecs/ingestion/...`).
   Read that stream directly — `aws logs tail` drowns in the running service.

Working recipe (verified repeatedly, 2026-09):
```sh
export AWS_PROFILE=economicbridge AWS_DEFAULT_REGION=eu-west-1 MSYS_NO_PATHCONV=1
B64=$(python -c "import ast,base64,io;print(base64.b64encode(ast.unparse(ast.parse(io.open('q.py',encoding='utf-8').read())).encode()).decode())")
cat > ovr.json <<JSON
{"containerOverrides":[{"name":"ingestion","environment":[{"name":"PYTHONPATH","value":"/app"}],
 "command":["sh","-lc","cd /app && echo $B64 | base64 -d > /tmp/q.py && python /tmp/q.py"]}]}
JSON
TASK=$(aws ecs run-task --cluster economicbridge-staging-cluster \
  --task-definition economicbridge-staging-ingestion:5 --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet>],securityGroups=[<sg>],assignPublicIp=ENABLED}" \
  --overrides file://ovr.json --query 'tasks[0].taskArn' --output text)
ID=${TASK##*/}
aws ecs wait tasks-stopped --cluster economicbridge-staging-cluster --tasks "$ID"
aws logs get-log-events --log-group-name "/ecs/economicbridge-staging/ingestion" \
  --log-stream-name "ingestion/ingestion/$ID" --start-from-head --limit 80 \
  --query 'events[].message' --output text | tr '\t' '\n'
```

`ast.unparse` strips docstrings — necessary because **ECS `--overrides` is
capped at 8192 characters**.

Discover subnets/SG rather than trusting stale IDs:
```sh
aws ecs describe-services --cluster economicbridge-staging-cluster \
  --services economicbridge-staging-ingestion \
  --query 'services[0].networkConfiguration.awsvpcConfiguration'
```

**asyncpg needs real `date` objects** for DATE bind params — passing
`'2026-09-01'` raises `'str' object has no attribute 'toordinal'`.

---

## 5. Automation inventory — what runs unattended

**In-process APScheduler in the ingestion service** (`apps/ingestion/scheduler.py`,
14 jobs). It is NOT EventBridge — there are no ECS scheduled rules for these, so
changing a cadence requires a code change + ingestion deploy.

| UTC | Job |
|-----|-----|
| 06:00 | NASA FIRMS fire ingest (`MODIS_NRT`) |
| 06:30 | conflict pipeline (`conflict_pipeline_v1`) |
| 07:00 | encroachment detector (`encroachment_detector_v1`) |
| 07:30 | ShockGuard SAR/NDVI scan (`shockguard_scan_v1`) |
| 08:00 | IMERG daily rainfall advisory (`rainstorm_scan_v1`) |
| 08:30 | **storm scan, half-hourly IMERG** (`storm_scan_v1`) |
| 09:30 | feed-health watchdog → email digest |
| 15m | satellite pass imagery |
| weekly | satellite-obs · WorldPop · poverty VIIRS |
| monthly | mobility · aid · skills · food prices (5th) |

Introspect and fire manually:
```
GET  /ingestion/api/v1/scheduler/jobs
POST /ingestion/api/v1/scheduler/jobs/{id}/run
GET  /ingestion/api/v1/scheduler/runs/recent
```

**Whole-LGA land-change scan — MANUAL, seasonal, not scheduled.** It is not in
APScheduler and must not be: a pass takes hours and would starve the live feeds
that share the ingestion service. Run it as a one-shot Fargate task:

```sh
python -m scripts.run_land_change --tenant kebbi            # writes
python -m scripts.run_land_change --tenant kebbi --no-write # rehearse, no DB needed
```
with `"cpu":"1024","memory":"8192"` in the run-task overrides — **not 4096**. The scan reads three seasons and each holds its own accumulators; at 4 GB the kernel killed both the Niger and the zamfara/plateau/fct runs on their largest LGAs, and the only evidence is a bare `Killed` in the log. **It is not a
shadow job any more — a run changes what the live Farmland panel shows.** Per
LGA it replaces that LGA's rows in `land_change_hotspots`, upserts one
`lga_season_vegetation` row per season (with the Esri land-cover split since
migration 0050 — the column must exist before the scan runs, or every write
fails), and replaces that LGA's `alert_events` rows tagged
`model_version='land_change_v1'` with the persistent bare-on-farmland patches,
which the panel reads. It stamps `land_change_v1` in `ingestion_runs`; that
source has a staleness budget in `FEED_MAX_AGE_HOURS` but is deliberately
ABSENT from `LIVE_SCAN_SOURCES`. Pass `--end YYYY-MM-DD` so every group reads
to the same date. Run it AFTER the rains, when October is available
to both years: in mid-September the 2025 baseline over Benue averages 0.39
clear looks per pixel and the LGA honestly reports 0% observed.

**Economic Visibility (village light) — one round a year, in late September.**
Measures night light and people at every real GRID3 village into
`tenant_<id>.village_light` (migration 0054): VIIRS 12-night medians on dry
(to 20 Mar) and wet (to 14 Sep) nights of the same year, HRSL people and
under-fives assigned to the nearest village. Rounds are ADDED, never
overwritten — next year's round shows which villages became lit. One-shot
ingestion task at 8 GB, about 4 minutes per state (two tasks in parallel took
~25 min for all eight in 2026):
```sh
python -m scripts.run_village_light --tenant kebbi,zamfara,fct,nasarawa --year 2027
python -m scripts.run_village_light --tenant kaduna,niger,benue,plateau --year 2027
```
The old generated poverty points (poverty_villages) and their two weekly jobs
are retired — do not re-schedule them; a test keeps them off.

**Village names for field directions — refresh twice a year.** Every Farmland
alert carries its nearest named village and ward ("1.0 km SE of Kurmin Kaya ·
Libata ward") from `public.named_settlements` (migration 0052), our own copy of
GRID3 NGA Settlement Names (CC BY 4.0 — the credit line must stay on screen).
Refresh with a one-shot ingestion task, default memory, about two minutes:
```sh
python -m scripts.load_grid3_settlements            # 8 Nigerian pilots, upsert only
python -m scripts.load_grid3_settlements --dry-run  # download + count, no DB
```
It never deletes; a changed name keeps its old version in `deleted_records`.
A new pilot state needs its GRID3 name (FCT is `Fct`) passed with `--states`.

> **On Windows the AWS CLI cannot read `--overrides file:///tmp/...`** — it is a
> Windows binary and `/tmp` is not a Windows path. Write the JSON into the
> scratchpad and pass its Windows path.

**Feed-health watchdog** (`apps/api/services/feed_health.py`) emails a digest at
09:30 UTC. It polices two things: staleness (`FEED_MAX_AGE_HOURS`) and real-row
stock (`STOCK_PROBES`). It exists because a bug once deleted real satellite
readings daily for sixteen days while every status said `succeeded`.

> **Rule:** a new scheduled feed must be added in THREE places or it is
> half-wired — `LIVE_SCAN_SOURCES` (routers/shockguard.py, so the panel shows
> it), `FEED_MAX_AGE_HOURS` (so staleness is policed), and it must stamp
> `public.ingestion_runs`. A test now enforces the first two agree; the storm
> scan shipped missing the second and the watchdog caught it the next morning.

**Farmer SMS is LIVE and fully automatic** — rainfall advisories dispatch to
Kebbi cooperative leaders with no human in the loop, via Termii (sender ID
`Ecobridge`). Guards + the stop procedure are in the assistant memory note
`project_farmer_sms_automation`; the switch is a tfvars flag + apply + rolling
the notifications service. **Never widen the automated audience casually.**

---

## 6. Module reality — what is REAL, and what each may claim

| Module | Live data | Caveat you must not drop |
|---|---|---|
| Farmland | S1 SAR + S2 NDVI + FIRMS + VIIRS, per-LGA all states | The "48–72hr conflict window" was NEVER validated. Do not restate it. |
| ShockGuard flood/drought | per-LGA S1/S2 + cited historical | Drought has no ground truth — never quote an accuracy figure. |
| **Storm engine** | GPM IMERG half-hourly, all 447 LGAs | **Measurement feed, not alerting.** See below. |
| Economic Visibility (poverty) | real VIIRS radiance + WorldPop | **Coordinates and names are synthetic.** See below. |
| CropGuard | trained ResNet-50 + live CDSE Farm Check | 12/12 on lab imagery, 0/3 on field photos. Never quote 0.872 bare. |
| Mobility / Skills / Aid | World Bank / UNICEF GIGA / OCHA HAPI | — |

### Storm engine (2026-09-02, commits 74ef065 → 6e2df74)
Reconstructs storms from half-hourly rate because a calendar day is not a storm
— Abuja flooded 30/31 Aug and a 21:00–00:30 WAT storm was split across two UTC
granules, so nothing could fire. Reports what fell, how fast, how it ranks
against that LGA's own record.

**Measured walk-forward over the 28-day backfill: 23.1% fire rate** (125 of 540
rateable observations). That is 2.3× what a stationary p90 gives — the record
carries a seasonal slope, the same trap as the drought detector. **Do not send
storm alerts to anyone, and never quote an accuracy figure**, until the record
is deep enough for per-LGA seasonality. Details:
`docs/` + assistant memory `reference_storm_baseline_stats`.

### Economic Visibility — the open honesty problem (found 2026-09-04)
The **numbers are real** (447 `viirs_v2` rows with genuine VIIRS radiance +
WorldPop). The **locations are not**:

- Coordinates are LGA polygon centroids + random jitter of ±0.125° lon /
  ±0.10° lat ≈ **±13.6 km / ±11.1 km** (`apps/api/scripts/seed_poverty_villages.py:123`).
- `settlement_name` is the template `f"{lga} settlement {i+1}"` — **all 1,341
  rows across every tenant and every source**, zero real place names.
- `poverty_ingest.py:152` deliberately reuses the seed geometry, so live VIIRS is
  sampled at a random point up to 13 km from the LGA centre. The reading is real;
  the claim that it describes a settlement is not.
- `PovertyMap.tsx` renders that synthetic name as an always-on deck.gl TextLayer.

**Do not fix this with reverse geocoding** — naming whatever sits near a
fabricated point launders it into an apparently-verified place name. The honest
fix is to present the module at its true unit (LGA, one row per LGA). Real
settlement-level poverty needs real settlement points FIRST (GRID3 publishes
them for Nigeria; **verify the licence permits commercial use**), then sample
VIIRS/WorldPop *at* those points — names then come free with the geometry.
Investigation was cut short by a session limit; three angles remain
(existing geo assets, sibling patterns, external gazetteers).

### Farmland + ShockGuard — the 0.56% problem (found 2026-09-15, fix IN PROGRESS)
Every "per-LGA" sweep measures ONE 3 x 3 km box at the LGA centroid: 4,023 km²
of the 715,731 km² the 447 pilot LGAs cover (0.56%). That is why the same
places kept resurfacing — they were the only places looked at. Enlarging the
box cannot fix it (the Copernicus Statistical API returns one average per box,
and whole LGAs are ~178x the Processing Units).

**Approved fix:** pixel-level change detection over whole LGAs, read from the
open Sentinel archive (no PU meter). Step 1 shipped: `data/lga_boundaries.geojson`,
`sources/lga_boundaries.py`, `sources/open_archive.py`, `sources/cog_window.py`.
Operator constraints: Nigeria first; Ghana + Senegal configured but held via
`OPEN_ARCHIVE_TENANTS`; existing feeds untouched; no UI change — new detections
go to a shadow table until proven, then into `alert_events` the map already reads.

Facts a successor must not re-derive: Sentinel-1 RTC on Planetary Computer is
**linear** gamma0 (convert with `cog_window.to_db`); radar must only be compared
within one orbit (`Scene.orbit_key`); a whole LGA reads in ~1.5 s at 30 m from
eu-west-1; optical is 55-93% cloud in the wet season.

**Live defect found on the way:** 6 concave LGAs (Bungudu, Buruku, 4 in Ghana)
have a centroid OUTSIDE the LGA, 8-11 km into a neighbour, so every
centroid-sampled feed reads the neighbour there. Listed in the boundary file's
`concave_lgas`. Correcting `lga_centroids.json` shifts those LGAs' baselines —
an operator decision.

---

## 7. Open items

**Code, unblocked:**
0. **Whole-LGA change detection, steps 2-3** (§6 above) — detector in parallel
   with the current feed into a shadow table, walk-forward check, then switch.
1. Poverty module honesty fix (§6) — the largest outstanding correctness issue.
2. Storm seasonality — per-LGA monthly climatology once the record deepens.
3. Farmland panel still renders "48–72HR CONFLICT-RISK WINDOW" + per-alert ETA.
   The claim was scrubbed from every deck and still ships in the UI.
4. Panel should distinguish "scanned, nothing found" / "cloud-obscured" /
   "last confirmed N days ago" — partially done for storms, not elsewhere.

**Operator / external:**
5. **Earthdata token expires ~2026-09-18** — it powers IMERG, which auto-sends
   farmer SMS. Rotate at urs.earthdata.nasa.gov → `put-secret-value` on
   `/economicbridge/staging/earthdata/token` → force-new-deployment ingestion.
6. NASRDA — re-issue invites ~12 Sept (Dr Ibrahim LAST), confirm 15 Sept.
7. NAIC letter send; WFP demo video / deck / LOI / budget.
8. RDS password rotation; LGA boundary polygons; SystemStatus widget is hardcoded.

---

## 8. Local dev + gotchas

- Ports: frontend 3001, api 8000, ingestion 8001, ml 8002, notifications 8003.
- **Python env split:** api/ingestion/notifications use `apps/api/.venv`
  (shapely/rasterio/h5py); ML + crop training use global Python (torch).
  Wrong env → request-time 500.
- Local Postgres on `localhost:5434`; `DATABASE_URL` in root `.env`.
- **A local dev DB is reachable from tests.** A unit test that touches the
  session factory will silently pass locally by writing into it, then red in CI.
  Stub the session factory in unit tests.
- Never run `next build` while `next dev` runs (freezes HMR). Kill ALL uvicorn
  child PIDs on restart.
- CI fresh-resolves unpinned deps; reproduce CI-only failures in a throwaway venv.
- `.coveragerc`: inline `;` comments are NOT stripped inside multi-line lists.

---

## 9. Working conventions that keep being re-learned

- **Never claim something shipped from a 200 or a `succeeded`.** Verify the
  effect: read CloudWatch, query the DB, check task `startedAt`. A feed that
  reports success while writing nothing is the failure mode this project has
  hit most.
- **Never present a statistic without the sample behind it.** "99th percentile"
  over 21 days is a statement about three weeks.
- **New UI goes INSIDE an existing container** (tab/toggle beside the map),
  reusing `fp-alert-*` classes. Zero added vertical footprint unless asked.
- **Diagnose before declaring a blocker.** The git-push "blocker" in §3 was a
  lookup miss that cost a session.

---

## 10. Pointers / source of truth

- `CLAUDE.md` — master spec & conventions (read fully each session). NOTE: its
  §2 wrongly implies Citadel was deployed for Kebbi State. It was built and
  pitched; they never responded. Never describe it as deployed.
- `docs/ARCHITECTURE.md`, `docs/PROGRESS.md` — architecture + narrative.
- `docs/runbooks/operations.md` · `.github/workflows/README.md`.
- **Assistant session memory** lives at `~/.claude/projects/<project>/memory/`
  on the *original machine* and does NOT travel — **this doc + the git repo are
  the portable handoff.** On a new machine start from `CLAUDE.md` + this file.
