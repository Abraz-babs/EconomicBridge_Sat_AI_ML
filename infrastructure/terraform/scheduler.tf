# EconomicBridge — scheduled report emails.
#
# An EventBridge Scheduler fires daily and runs the api task definition with a
# command override (`python -m scripts.send_scheduled_reports`). The job only
# sends subscriptions that have come due, so a daily trigger is safe + cheap
# (one short Fargate task/day). Created only when enable_scheduled_reports=true.
#
# Toggle/cadence: var.enable_scheduled_reports, var.scheduled_reports_schedule.

# ─── IAM role EventBridge Scheduler assumes to run the task ────────────────

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "reports_scheduler" {
  count              = var.enable_scheduled_reports ? 1 : 0
  name               = "${local.name_prefix}-reports-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json

  tags = { Name = "${local.name_prefix}-reports-scheduler" }
}

data "aws_iam_policy_document" "reports_scheduler" {
  # RunTask on any revision of the api task-definition family.
  statement {
    sid       = "RunReportTask"
    actions   = ["ecs:RunTask"]
    resources = ["arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-api:*"]
    condition {
      test     = "ArnLike"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }
  # Pass the task's execution + task roles to ECS at launch.
  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.ecs_execution.arn, aws_iam_role.ecs_task["api"].arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "reports_scheduler" {
  count  = var.enable_scheduled_reports ? 1 : 0
  name   = "${local.name_prefix}-reports-scheduler"
  role   = aws_iam_role.reports_scheduler[0].id
  policy = data.aws_iam_policy_document.reports_scheduler.json
}

# ─── The schedule ──────────────────────────────────────────────────────────

resource "aws_scheduler_schedule" "reports" {
  count                        = var.enable_scheduled_reports ? 1 : 0
  name                         = "${local.name_prefix}-scheduled-reports"
  description                  = "Scheduled report emailer. Networking repaired 2026-07-29: was on private subnets with no NAT, so every run died at ResourceInitializationError and it had never once executed."
  schedule_expression          = var.scheduled_reports_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.reports_scheduler[0].arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.service["api"].arn
      launch_type         = "FARGATE"
      task_count          = 1

      # Budget mode (no NAT): run in public subnets with a public IP, exactly
      # as ecs.tf:215 does for the services. Hardcoding private+false here is
      # what silently broke the reports job — with no NAT gateway the task
      # cannot reach Secrets Manager or ECR, so it dies at
      # ResourceInitializationError before the container ever starts, writes no
      # logs, and looks from the console like a schedule that simply never ran.
      network_configuration {
        subnets          = var.use_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
        security_groups  = [aws_security_group.ecs_tasks.id]
        assign_public_ip = var.use_nat_gateway ? false : true
      }
    }

    # Override the container command to run the report-emailer instead of uvicorn.
    input = jsonencode({
      containerOverrides = [
        {
          name    = "api"
          command = ["python", "-m", "scripts.send_scheduled_reports"]
        }
      ]
    })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }

  # The deploy workflow owns the revision. Without this, every CI deploy leaves
  # a spurious diff here and an unrelated apply would pin the schedule back to
  # a stale task definition.
  lifecycle {
    ignore_changes = [target[0].ecs_parameters[0].task_definition_arn]
  }
}

# ─── Feed-health watchdog ──────────────────────────────────────────────────
#
# Runs `python -m scripts.check_feed_health` daily on the api task. It emails
# ONLY on findings, so anything arriving in the inbox means something needs a
# look, and silence is a real signal rather than an absent one.
#
# It exists because in July 2026 the encroachment sweep ran daily for about
# sixteen days, recorded `succeeded` every time, and deleted 306 of 447 real
# crop_health NDVI readings while doing it. Nothing was red, because nothing
# was watching. See apps/api/services/feed_health.py.
#
# The api task definition is the target because it is the one carrying
# RESEND_API_KEY; the ingestion service holds the scheduler for the feeds
# themselves but has no mail credentials.
#
# Reuses the reports role rather than minting a second identical one — same
# principal, same cluster, same task family, same PassRole set.

resource "aws_scheduler_schedule" "feed_health" {
  count                        = var.enable_feed_health_watchdog ? 1 : 0
  name                         = "${local.name_prefix}-feed-health"
  description                  = "Daily feed-health watchdog. Emails super-admin ONLY on findings. Created via CLI 2026-07-29 because terraform apply carries unrelated drift."
  schedule_expression          = var.feed_health_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.reports_scheduler[0].arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.service["api"].arn
      launch_type         = "FARGATE"
      task_count          = 1

      # Budget mode (no NAT): run in public subnets with a public IP, exactly
      # as ecs.tf:215 does for the services. Hardcoding private+false here is
      # what silently broke the reports job — with no NAT gateway the task
      # cannot reach Secrets Manager or ECR, so it dies at
      # ResourceInitializationError before the container ever starts, writes no
      # logs, and looks from the console like a schedule that simply never ran.
      network_configuration {
        subnets          = var.use_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
        security_groups  = [aws_security_group.ecs_tasks.id]
        assign_public_ip = var.use_nat_gateway ? false : true
      }
    }

    input = jsonencode({
      containerOverrides = [
        {
          name    = "api"
          command = ["python", "-m", "scripts.check_feed_health"]
        }
      ]
    })

    # No retry: a re-run would just re-send the same digest. The next day's
    # run is the retry, and a watchdog that double-mails trains you to ignore it.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }

  # See the note on the reports schedule: CI owns the revision, not Terraform.
  lifecycle {
    ignore_changes = [target[0].ecs_parameters[0].task_definition_arn]
  }
}
