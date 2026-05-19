# EconomicBridge — IAM roles for ECS + RDS.
#
# Two distinct ECS roles per AWS best practice:
#
#   1. Execution role  — used by the ECS agent to pull images from ECR,
#                        write logs to CloudWatch, and fetch secrets from
#                        Secrets Manager. Not visible to the running task.
#   2. Task role       — assumed by the application code at runtime. This
#                        is what boto3 inside the container sees. Scoped
#                        to just what the app needs.
#
# RDS gets a separate role for enhanced monitoring (60s metric granularity).

# ─── ECS task execution role (shared by all services) ─────────────────

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = {
    Name = "${local.name_prefix}-ecs-execution"
  }
}

# AmazonECSTaskExecutionRolePolicy covers ECR pull + CloudWatch Logs write.
resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Additional inline policy: read the secrets we created in secrets.tf so
# the ECS agent can inject them as env vars into the task definition.
data "aws_iam_policy_document" "ecs_execution_secrets" {
  statement {
    sid     = "ReadEconomicBridgeSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.rds_password.arn],
      [for s in aws_secretsmanager_secret.external : s.arn],
    )
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name   = "${local.name_prefix}-ecs-execution-secrets"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_secrets.json
}

# ─── ECS task role (per service — least-privilege) ────────────────────
# A separate task role per service so we can give the ingestion service
# S3 write access without also giving the frontend the same.

resource "aws_iam_role" "ecs_task" {
  for_each = local.services

  name               = "${local.name_prefix}-${each.key}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = {
    Name    = "${local.name_prefix}-${each.key}-task"
    Service = each.key
  }
}

# Inline policy per service. For now most services need the same:
#   - read their own secrets at runtime (in addition to env var injection)
#   - write to their CloudWatch log group
# Future: ingestion gets s3:PutObject on a tenant-prefixed bucket.
data "aws_iam_policy_document" "ecs_task_base" {
  for_each = local.services

  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.external : s.arn]
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${local.name_prefix}/${each.key}:*"]
  }
}

resource "aws_iam_role_policy" "ecs_task_base" {
  for_each = local.services

  name   = "${local.name_prefix}-${each.key}-task-base"
  role   = aws_iam_role.ecs_task[each.key].id
  policy = data.aws_iam_policy_document.ecs_task_base[each.key].json
}

# ─── RDS enhanced monitoring role ────────────────────────────────────

data "aws_iam_policy_document" "rds_monitoring_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rds_monitoring" {
  name               = "${local.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.rds_monitoring_assume.json

  tags = {
    Name = "${local.name_prefix}-rds-monitoring"
  }
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
