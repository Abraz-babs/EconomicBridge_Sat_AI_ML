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

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.ecs_tasks.id]
        assign_public_ip = false
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
}
