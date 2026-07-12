# RDS Restore Drill — Runbook

Proves the database backup chain actually restores, measures RPO/RTO, and
smoke-tests the restored data — without touching production. Repeat
**quarterly** (next due: **October 2026**) and after any major schema change.
An untested backup is a hope, not a plan.

## Measured results — drill of 12 July 2026 (baseline)

| Metric | Measured | Meaning |
|---|---|---|
| **RPO evidence** | `LatestRestorableTime` trailed wall-clock by **~4 minutes** | Point-in-time recovery loses at most minutes of writes |
| **RTO (restore)** | restore started 16:17:30 → available 16:40:06 UTC = **22 min 36 s** | 20 GB, db.t4g.micro, single-AZ, eu-west-1 |
| **RTO (verified)** | + ~6 min smoke test = **≈ 30 min** start → *proven-good* database | The honest number to quote in an SLA conversation |
| Smoke result | **PASS** — 10/10 tenant schemas, 652 ingestion runs (latest 14:58 same day), Kebbi 26 alerts, FCT 6 alerts + 12 farm-check records | Data whole and fresh |
| Drill finding | Backup retention was **1 day** → raised to **7 days** during the drill | Free at our size (retained backup ≤ 100 % of allocated storage) |

Full-service RTO (fresh RDS + repointing services) would add DNS/secret
updates and service restarts — estimate **≤ 1 hour** total. The SLA's
Critical restore target (24 h) has ~23 h of margin.

## Prerequisites

- AWS CLI with the `economicbridge` profile (deployer user has all required
  permissions: `rds:*`, `ecs:RunTask`, `iam:PassRole`, `logs:GetLogEvents`).
- Git Bash: `export MSYS_NO_PATHCONV=1`.

## Procedure

### 1. Record the facts (RPO evidence)

```bash
aws rds describe-db-instances --region eu-west-1 \
  --db-instance-identifier economicbridge-staging-postgres \
  --query "DBInstances[0].{latestRestorable:LatestRestorableTime,retention:BackupRetentionPeriod,subnetGrp:DBSubnetGroup.DBSubnetGroupName,sg:VpcSecurityGroups[0].VpcSecurityGroupId}"
```

Note `LatestRestorableTime` vs now — that gap is the live RPO. Retention must
read **7** (raised 2026-07-12; if it ever reads lower, raise it back and
investigate who changed it).

### 2. Restore to a scratch instance (start the RTO clock)

```bash
date -u   # ← RTO clock start
aws rds restore-db-instance-to-point-in-time --region eu-west-1 \
  --source-db-instance-identifier economicbridge-staging-postgres \
  --target-db-instance-identifier eb-restore-drill-YYYYMMDD \
  --use-latest-restorable-time \
  --db-instance-class db.t4g.micro \
  --db-subnet-group-name economicbridge-staging-rds-subnets \
  --vpc-security-group-ids <same SG as source, step 1> \
  --no-multi-az --no-publicly-accessible \
  --tags Key=purpose,Value=restore-drill
aws rds wait db-instance-available --region eu-west-1 \
  --db-instance-identifier eb-restore-drill-YYYYMMDD
date -u   # ← restore-available time; grab the endpoint:
aws rds describe-db-instances --region eu-west-1 \
  --db-instance-identifier eb-restore-drill-YYYYMMDD \
  --query "DBInstances[0].Endpoint.Address" --output text
```

Same subnet group + security group as the source so the one-shot ECS task can
reach it. Never public.

### 3. Smoke-test from inside the VPC (no credentials leave Secrets Manager)

Reuses the `ecs_migrate.sh` pattern: a one-shot Fargate task on the **api**
task definition (which injects `DATABASE_URL` from Secrets Manager), command
overridden to a Python check that swaps only the hostname to the scratch
endpoint (passed as the plain env var `SCRATCH_HOST` — never a secret in task
overrides). The check asserts:

- `SHOW server_version` matches production (16.x);
- all 10 `tenant_*` schemas exist;
- `public.ingestion_runs` row count > 0 and `max(started_at)` is recent
  (close to the restore point);
- per spot-check tenants (kebbi, fct): `alert_events` count + newest
  `created_at`, and `farm_checks` count where the table exists.

PASS = exit 0 + `RESTORE-SMOKE OK` in the api log group
(`/ecs/economicbridge-staging/api`, stream `api/api/<taskId>`).

### 4. Delete the scratch (stop the cost)

```bash
aws rds delete-db-instance --region eu-west-1 \
  --db-instance-identifier eb-restore-drill-YYYYMMDD \
  --skip-final-snapshot --delete-automated-backups
```

Total drill cost: well under $1 (≈½ hour of db.t4g.micro + 20 GB-hours).

### 5. Record the drill

Update the results table above with the new date/timings, commit, and note
any findings (like the retention fix) as their own follow-ups.

## Real-disaster variant (actual data loss)

1. Restore as above but to `economicbridge-staging-postgres-recovered`,
   choosing `--restore-time` just before the incident instead of
   `--use-latest-restorable-time`.
2. Smoke-test it (step 3) **before** switching anything.
3. Point services at it: update the DB endpoint in the Secrets Manager
   `DATABASE_URL` secret(s), then force new deployments of all five services
   (`aws ecs update-service --force-new-deployment`).
4. Keep the damaged instance stopped (not deleted) until the incident
   post-mortem completes.
5. Mirror the new instance identifier in Terraform before the next
   `terraform apply`.

## Standing configuration (verified 2026-07-12)

- Source: `economicbridge-staging-postgres` — Postgres 16.13, db.t4g.micro,
  20 GB, single-AZ, eu-west-1, retention **7 days**, PITR enabled.
- External uptime monitoring: 5 Route 53 health checks + `uptime-eb-*`
  CloudWatch alarms (us-east-1) → SNS `eb-uptime-alerts` → email.
- Drift note: retention change + health checks were applied via CLI; mirror
  in Terraform when next touching `infrastructure/terraform`.
