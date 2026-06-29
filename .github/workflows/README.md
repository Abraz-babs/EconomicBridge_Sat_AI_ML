# EconomicBridge — GitHub Actions

| Workflow         | Trigger                              | What it does                                              |
|------------------|--------------------------------------|-----------------------------------------------------------|
| `ci.yml`         | PR + push to `main`                  | Lint + pytest + frontend build + bandit/semgrep           |
| `terraform.yml`  | PR + push touching `terraform/`      | fmt + validate; on PR also `plan` against staging          |
| `deploy.yml`     | Manual (`workflow_dispatch`)         | Build → push to ECR → `aws ecs update-service` rolling    |

CI runs on every PR and is credential-free (no AWS access).
Terraform plan and deploy authenticate to AWS via **OIDC** — there are
no long-lived access keys stored in GitHub.

---

## One-time AWS setup for OIDC

Run these once as the operator (`economicbridge-deployer` IAM user or
root) before the workflows can talk to AWS.

### 1. Register GitHub as an OIDC identity provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

(The thumbprint is GitHub's well-known root CA fingerprint.)

### 2. Create the `github-actions-terraform-plan` role (read-only)

Trust policy — replace `Abraz-babs/EconomicBridge_Sat_AI_ML` with your
GitHub org/repo:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::198566079411:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:Abraz-babs/EconomicBridge_Sat_AI_ML:*"
      }
    }
  }]
}
```

Attach the AWS-managed `ReadOnlyAccess` policy plus an inline policy
allowing access to the Terraform state backend:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::economicbridge-tf-state-198566079411",
        "arn:aws:s3:::economicbridge-tf-state-198566079411/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"],
      "Resource": "arn:aws:dynamodb:eu-west-1:198566079411:table/economicbridge-tf-locks"
    }
  ]
}
```

### 3. Create the `github-actions-deploy` role (ECR + ECS)

Same trust policy as above. Inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EcsDeploy",
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassRoleToEcs",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::198566079411:role/economicbridge-*-ecs-execution",
        "arn:aws:iam::198566079411:role/economicbridge-*-*-task"
      ]
    }
  ]
}
```

Lock the trust policy down further for production by setting `sub` to
something like `repo:org/repo:environment:production` once you've
created a GitHub environment with reviewer protection.

---

## GitHub-side setup

### Secrets (Repo → Settings → Secrets → Actions)

| Name                        | Used by      | Value                                                |
|-----------------------------|--------------|------------------------------------------------------|
| `NEXT_PUBLIC_MAPBOX_TOKEN`  | `deploy.yml` | Mapbox public token (pk.*) — baked into frontend     |

(No `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — OIDC replaces them.)

### Environments (Repo → Settings → Environments)

Create two environments:

- **staging** — no required reviewers, can be triggered by anyone with
  write access.
- **production** — required reviewers = at least one repo admin. This
  makes `deploy.yml` *pause* before the `build` job and wait for human
  approval when targeting production.

---

## Triggering a deploy

```
Repo → Actions → Deploy → Run workflow
  Environment: staging
  Services:    all   (or "api,frontend")
  Image tag:   <leave blank to use commit SHA>
```

The workflow:
1. Resolves inputs → region, services array, image tag, role ARN
2. Builds each service in parallel and pushes to its ECR repo
3. Calls `aws ecs update-service --force-new-deployment` per service
4. Waits for each service to reach steady state before moving on

A rollback is just re-running the workflow with `image_tag` set to a
known-good older SHA.

---

## What CI does NOT do

- **`terraform apply`** — applied from a trusted workstation, not CI.
- **Auto-deploy on merge** — currently manual. Flip to auto by removing
  `workflow_dispatch` from `deploy.yml` and adding `push: branches: [main]`
  once you trust staging enough.
- **Database migrations** — `alembic upgrade head` is not run by the
  deploy workflow. Apply them with the one-shot ECS migrate task instead:

  ```sh
  make ecs-migrate ENV=staging          # or: scripts/ecs_migrate.sh staging
  ```

  This launches a throwaway Fargate task that reuses the api task definition
  (same image, DATABASE_URL secret, subnets + SG) but overrides the command to
  run `alembic upgrade head` — so it reaches the private RDS from inside the
  VPC. Run it AFTER the Deploy workflow has pushed the image containing the new
  migration. Needs creds with `ecs:RunTask` / `DescribeTasks`, `iam:PassRole`
  on the api task roles, and `logs:GetLogEvents` (the `economicbridge-deployer`
  user has these; the CI OIDC role does not — wire it into CI later by adding
  those actions to `github_oidc.tf`).
