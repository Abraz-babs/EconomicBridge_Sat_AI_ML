# EconomicBridge — GitHub Actions OIDC federation.
#
# Lets the repo's workflows assume short-lived AWS roles WITHOUT long-lived
# access keys stored as GitHub secrets:
#   * github-actions-deploy          — deploy.yml: build/push images to ECR +
#                                      roll ECS services.
#   * github-actions-terraform-plan  — terraform.yml: read-only plan on PRs.
#
# Trust is scoped to THIS repository (any branch/event) via the `sub` claim.

locals {
  github_repo = "Abraz-babs/EconomicBridge_Sat_AI_ML"
}

# One provider per account; GitHub's OIDC issuer. AWS validates the cert chain
# against trusted roots, so the thumbprint is effectively a placeholder, but
# the API still requires one.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name = "${local.name_prefix}-github-oidc"
  }
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_repo}:*"]
    }
  }
}

# ─── Deploy role (deploy.yml) ──────────────────────────────────────────

resource "aws_iam_role" "github_deploy" {
  name               = "github-actions-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json

  tags = {
    Name = "${local.name_prefix}-github-deploy"
  }
}

data "aws_iam_policy_document" "github_deploy" {
  # ECR login is account-wide by design.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Push/pull only on this project's repos.
  statement {
    sid = "EcrPushPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [for r in aws_ecr_repository.service : r.arn]
  }

  # Rolling restarts on the project's ECS services only.
  statement {
    sid = "EcsRollingDeploy"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices",
    ]
    resources = [
      for k in keys(local.services) :
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/${local.name_prefix}-${k}"
    ]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name_prefix}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

# ─── Read-only plan role (terraform.yml, PRs) ──────────────────────────

resource "aws_iam_role" "github_plan" {
  name               = "github-actions-terraform-plan"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json

  tags = {
    Name = "${local.name_prefix}-github-plan"
  }
}

resource "aws_iam_role_policy_attachment" "github_plan_readonly" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Plan still needs to read/lock the Terraform state backend.
data "aws_iam_policy_document" "github_plan_state" {
  statement {
    sid     = "StateRead"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::economicbridge-tf-state-${data.aws_caller_identity.current.account_id}",
      "arn:aws:s3:::economicbridge-tf-state-${data.aws_caller_identity.current.account_id}/*",
    ]
  }
  statement {
    sid = "StateLock"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = [
      "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/economicbridge-tf-locks",
    ]
  }
}

resource "aws_iam_role_policy" "github_plan_state" {
  name   = "${local.name_prefix}-github-plan-state"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.github_plan_state.json
}
