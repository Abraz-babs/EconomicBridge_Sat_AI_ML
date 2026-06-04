# EconomicBridge — Terraform IaC

Production-grade AWS infrastructure for the EconomicBridge platform. One
stack, deployed twice via Terraform workspaces:

| Workspace    | Region        | Purpose                              |
|--------------|---------------|--------------------------------------|
| `staging`    | `eu-west-1`   | Pre-prod rehearsal, cheap, public-OK |
| `production` | `af-south-1`  | Data-sovereign, HA, deletion-protect |

State is stored remotely in `s3://economicbridge-tf-state-198566079411`
with DynamoDB locking via the `economicbridge-tf-locks` table.

---

## What this stack creates

- **VPC** — `/16` CIDR, public + private subnets across 2 AZs, IGW, NAT
  gateway(s), S3 gateway endpoint (saves NAT egress).
- **ECR** — 5 repositories (api, ingestion, ml, notifications, frontend),
  IMMUTABLE tags, scan-on-push, lifecycle = keep latest 20.
- **Secrets Manager** — RDS password (Terraform-generated) + 10
  external-provider secrets (Copernicus, NASA FIRMS, N2YO, Earth Engine,
  Mapbox, Claude, Termii, Twilio×2) created empty for operator to fill.
- **RDS PostgreSQL 16** — Multi-AZ, gp3 storage with autoscaling,
  encrypted at rest + TLS forced, PostGIS-ready parameter group,
  enhanced monitoring, performance insights.
- **ElastiCache Redis 7** — at-rest + in-transit encryption, single
  shard, replica enabled in production.
- **ALB** — path-based routing to 5 target groups, TLS-1.2+ if cert
  provided, otherwise HTTP-only (staging fallback).
- **ECS Fargate** — 1 cluster, 5 services, separate task role per
  service, CloudWatch container insights, autoscaling on CPU.
- **CloudWatch** — log group per service, alarms for ALB 5xx, ECS CPU,
  RDS CPU + storage, Redis CPU. Fan-out via SNS topic.

Resource count: ~80 resources. First `terraform apply` ≈ 25 minutes
(RDS provisioning is the slowest).

---

## Prerequisites

1. **AWS account + IAM user** with `AdministratorAccess`. Account ID is
   `198566079411`; access keys configured locally via `aws configure`.
2. **Terraform 1.9+** and **AWS CLI v2** on the operator's machine.
3. **State backend** already exists:
   - S3 bucket: `economicbridge-tf-state-198566079411` (versioned + encrypted)
   - DynamoDB table: `economicbridge-tf-locks` (PK `LockID`, string)

---

## First-time deploy (staging)

```bash
cd economic-bridge-project/infrastructure/terraform

# Initialise the backend + plugins
terraform init

# Create the staging workspace (state key already namespaced via workspace)
terraform workspace new staging

# Copy + edit tfvars
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # set alarm_email, acm_certificate_arn if you have one

# Plan + apply
terraform plan -out=tfplan
terraform apply tfplan
```

Apply takes 20–30 minutes. Watch for the RDS step — it's the long tail.

---

## After `terraform apply` — populate the external secrets

Terraform creates the secrets *empty* (placeholder value
`PLACEHOLDER_NOT_SET`). Populate them with real values:

```bash
aws secretsmanager put-secret-value \
  --secret-id /economicbridge/staging/nasa_firms/api_key \
  --secret-string '<the real key>' \
  --region eu-west-1

# Repeat for: copernicus/client_id, copernicus/client_secret,
# n2yo/api_key, earth_engine/service_account, mapbox/public_token,
# claude/api_key, termii/api_key, twilio/account_sid, twilio/auth_token
```

Or push everything from your local `.env` at once:

```bash
python populate_secrets.py --env staging --profile economicbridge
```

A `lifecycle.ignore_changes` on the secret version means Terraform won't
fight the operator on subsequent applies.

### Auth secrets

- **`auth/jwt_secret_key`** — *generated and owned by Terraform* (random 64-char
  string). Nothing to populate. Tainting + re-applying rotates it and
  invalidates all live sessions.
- **`auth/super_admin_password`** — operator-populated (above, or via
  `populate_secrets.py` from `SUPER_ADMIN_PASSWORD` in `.env`). Read once by the
  super-admin seed task below.

### SES (tenant invite emails)

Set `ses_sender_email` + `super_admin_email` in `terraform.tfvars` before apply.
Terraform creates an SES email identity; **AWS emails a verification link to that
address — click it** before invites can send. A new SES account is sandboxed
(only verified recipients) until you request production access. With
`ses_sender_email` unset, the API runs `EMAIL_BACKEND=console` (logs the
activation link instead of emailing it) so the stack still works.

---

## Pushing container images

```bash
# Get the URLs
terraform output -json ecr_repository_urls

# Authenticate Docker to ECR
aws ecr get-login-password --region eu-west-1 | \
  docker login --username AWS --password-stdin \
  198566079411.dkr.ecr.eu-west-1.amazonaws.com

# Build + tag + push (per service)
docker build -t economicbridge/api:latest apps/api
docker tag economicbridge/api:latest \
  198566079411.dkr.ecr.eu-west-1.amazonaws.com/economicbridge-staging/api:latest
docker push \
  198566079411.dkr.ecr.eu-west-1.amazonaws.com/economicbridge-staging/api:latest
```

ECS services will pull `:latest` on next deploy. Set `image_tag` to a
git SHA in CI/CD to make rollbacks possible.

---

## Database migrations + super-admin bootstrap

Run once after the first image is pushed (and after any migration-bearing
deploy). Both reuse the **api** task definition — `run-task` with a command
override — so they get the same `DATABASE_URL` + secrets the service has. Run
them in the private subnets with the ECS task security group:

```bash
CLUSTER=economicbridge-staging-cluster
TASKDEF=economicbridge-staging-api
SUBNET=$(terraform output -json private_subnet_ids | jq -r '.[0]')
SG=$(terraform output -raw ecs_tasks_security_group_id)   # see outputs.tf
NET="awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=DISABLED}"

# 1) Apply migrations (alembic upgrade head — includes 0028 auth tables)
aws ecs run-task --cluster $CLUSTER --launch-type FARGATE \
  --task-definition $TASKDEF --network-configuration "$NET" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","alembic","upgrade","head"]}]}' \
  --region eu-west-1

# 2) Seed the platform super-admin (reads SUPER_ADMIN_EMAIL + the
#    auth/super_admin_password secret already injected into the api task)
aws ecs run-task --cluster $CLUSTER --launch-type FARGATE \
  --task-definition $TASKDEF --network-configuration "$NET" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","scripts.seed_super_admin"]}]}' \
  --region eu-west-1

# 3) Seed the 10 pilot regions + their module entitlements
aws ecs run-task --cluster $CLUSTER --launch-type FARGATE \
  --task-definition $TASKDEF --network-configuration "$NET" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","scripts.seed_tenant_registry"]}]}' \
  --region eu-west-1

# 4) Seed the pilot PARTNER orgs (ECOWAS, NEMA — full access, no account yet;
#    invite them from Admin → Tenant Registry when the deal closes)
aws ecs run-task --cluster $CLUSTER --launch-type FARGATE \
  --task-definition $TASKDEF --network-configuration "$NET" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","scripts.seed_partners"]}]}' \
  --region eu-west-1
```

Watch the task in CloudWatch Logs (`/ecs/economicbridge-staging/api`). After
this, sign in at the dashboard with `super_admin_email` + the password you set —
that's the only account that can reach the admin panel and register tenants. The
pilots + partners are already in the registry; partners just need an Invite.

---

## Forcing a rolling deployment

```bash
aws ecs update-service \
  --cluster economicbridge-staging-cluster \
  --service economicbridge-staging-api \
  --force-new-deployment \
  --region eu-west-1
```

---

## Promoting to production

```bash
terraform workspace new production
cp terraform.tfvars.example prod.tfvars
$EDITOR prod.tfvars   # uncomment the PRODUCTION OVERRIDES block

terraform plan -var-file=prod.tfvars -out=prod.tfplan
terraform apply prod.tfplan
```

Production differences (already encoded in the override block):
- region `af-south-1` (Cape Town — data sovereignty per ADR-003)
- `single_nat_gateway = false` (one NAT per AZ)
- `rds_deletion_protection = true`
- 2 Redis nodes (primary + replica)
- 30-day backup retention
- min 2 / max 10 ECS tasks per service

---

## Tearing down (staging only)

```bash
terraform workspace select staging
terraform destroy
```

This will refuse on production because `rds_deletion_protection = true`
and the ALB has `enable_deletion_protection`. Both are intentional.

---

## File map

| File                       | What it owns                                       |
|----------------------------|----------------------------------------------------|
| `versions.tf`              | Required Terraform + provider versions             |
| `backend.tf`               | S3 + DynamoDB state backend (hardcoded)            |
| `providers.tf`             | AWS provider + default tags                        |
| `variables.tf`             | All input variables                                |
| `locals.tf`                | Services map + secret paths + CIDR computation     |
| `data.tf`                  | Account / region / AZ lookups                      |
| `network.tf`               | VPC, subnets, IGW, NAT, route tables, VPCE         |
| `security_groups.tf`       | ALB / ECS / RDS / Redis SGs (least-privilege)      |
| `ecr.tf`                   | 5 repos + lifecycle policies                       |
| `secrets.tf`               | RDS password + 10 external-provider secrets        |
| `iam.tf`                   | ECS execution + per-service task roles + RDS mon   |
| `rds.tf`                   | PostgreSQL 16 Multi-AZ + parameter group           |
| `redis.tf`                 | ElastiCache Redis 7 replication group              |
| `alb.tf`                   | ALB + 5 target groups + listeners + path rules     |
| `logs.tf`                  | CloudWatch log groups (1 per service)              |
| `ecs.tf`                   | Fargate cluster + 5 services + autoscaling         |
| `alarms.tf`                | CloudWatch alarms + SNS fan-out                    |
| `outputs.tf`               | All useful outputs (ALB DNS, ECR URLs, etc.)       |
| `terraform.tfvars.example` | Annotated tfvars template                          |

---

## Known limitations + TODO

- **No WAF**. Production should add `aws_wafv2_web_acl` in front of the
  ALB (AWS Managed Rules + rate-limiting).
- **No CloudFront**. Static frontend assets could be cached at edge —
  ~$5/mo for our traffic, saves latency for Lagos/Abuja users.
- **No Route 53**. Domain + hosted zone are owned outside Terraform; we
  just emit `alb_dns_name` for the operator to point a CNAME at.
- **No tenant onboarding automation**. New tenants are added via the
  `scripts/generate_tenant.py` flow which talks to the live API.
