# EconomicBridge — ECS Fargate cluster + 5 services + autoscaling.
#
# Pattern:
#   1 Fargate cluster
#   5 task definitions (one per service from locals.services)
#   5 services (each registered with the matching ALB target group)
#   5 autoscaling targets + 1 CPU-based scaling policy each
#
# Task env vars come from two places:
#   - Plain env vars in the container_definitions (DB host, Redis URL, etc.)
#   - `secrets` block which pulls live values from Secrets Manager. The
#     ECS agent reads them using the execution role at task-start time.

# ─── Cluster ───────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled" # Prometheus-style metrics, ~$2/mo/service
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ─── Task definitions ─────────────────────────────────────────────────
# Each service gets a fully-resolved JSON container definition.
# Env vars include DB / Redis connection strings derived from the
# Terraform-managed RDS + Redis resources, so a fresh deploy "just works"
# without manual env-file editing.

locals {
  # Connection strings reused across services that need them.
  database_url = "postgresql+asyncpg://${aws_db_instance.main.username}:${random_password.rds.result}@${aws_db_instance.main.endpoint}/${aws_db_instance.main.db_name}"
  redis_url    = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"

  # Public dashboard origin used to build invite/activation links. Defaults to
  # the ALB DNS over HTTPS; override with var.public_app_url once a custom
  # domain is in front.
  public_app_url = var.public_app_url != "" ? var.public_app_url : "https://${aws_lb.main.dns_name}"

  # Invite email goes out via SES only when a verified sender is configured;
  # otherwise the API falls back to 'console' (logs the link) so a deploy
  # without SES set up still works (invites just aren't emailed).
  email_backend = var.ses_sender_email != "" ? "ses" : "console"

  # api-only env: auth onboarding (invite email + super-admin bootstrap).
  api_extra_env = [
    { name = "EMAIL_BACKEND", value = local.email_backend },
    { name = "EMAIL_FROM", value = var.ses_sender_email },
    { name = "PUBLIC_APP_URL", value = local.public_app_url },
    { name = "SUPER_ADMIN_EMAIL", value = var.super_admin_email },
  ]

  # ml-only env: where to fetch the trained CropGuard weights at startup
  # (gitignored 94 MB artifact — lives in S3, not the image).
  ml_extra_env = [
    { name = "MODEL_S3_URI", value = "s3://${aws_s3_bucket.artifacts.bucket}/ml/crop_classifier.pth" },
  ]

  # notifications-only env: outbound SMS via Amazon SNS. The gateway resolves to
  # SNS when SNS_ENABLED=true; otherwise it falls back to the mock gateway, so a
  # deploy with SMS still off plans/runs cleanly.
  notifications_extra_env = [
    { name = "SNS_ENABLED", value = var.sms_sns_enabled ? "true" : "false" },
    { name = "SNS_REGION", value = var.aws_region },
    { name = "SNS_SENDER_ID", value = var.sms_sns_sender_id },
  ]

  # Plain (non-secret) env vars per service. We use a function-style
  # local so each container definition stays terse below.
  service_env = {
    for k, v in local.services : k => concat(
      [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "SERVICE_NAME", value = k },
        { name = "LOG_LEVEL", value = var.environment == "production" ? "INFO" : "DEBUG" },
      ],
      v.needs_db ? [{ name = "DATABASE_URL", value = local.database_url }] : [],
      v.needs_redis ? [{ name = "REDIS_URL", value = local.redis_url }] : [],
      # ALB path prefix the app must strip itself (see UrlPrefixStripMiddleware).
      lookup(v, "url_prefix", "") != "" ? [{ name = "URL_PREFIX", value = v.url_prefix }] : [],
      k == "api" ? local.api_extra_env : [],
      k == "ml" ? local.ml_extra_env : [],
      k == "notifications" ? local.notifications_extra_env : [],
    )
  }

  # Secrets injected via Secrets Manager. The agent fetches these at
  # task-start time using the execution role's GetSecretValue permission.
  # Format: list of {name, valueFrom = arn}. We attach the full set to
  # every service that touches external APIs (api, ingestion, notifications).
  # frontend + ml don't need third-party API keys yet.
  service_secrets = {
    api = concat(
      [for path in local.secret_paths : { name = local.secret_env_name[path], valueFrom = aws_secretsmanager_secret.external[path].arn }],
      [{ name = "JWT_SECRET_KEY", valueFrom = aws_secretsmanager_secret.jwt.arn }],
    )
    ingestion     = [for path in local.secret_paths : { name = local.secret_env_name[path], valueFrom = aws_secretsmanager_secret.external[path].arn } if can(regex("^(copernicus|nasa_firms|n2yo|earth_engine|giga|earthdata)/", path))]
    ml            = [for path in local.secret_paths : { name = local.secret_env_name[path], valueFrom = aws_secretsmanager_secret.external[path].arn } if can(regex("^claude/", path))]
    notifications = [for path in local.secret_paths : { name = local.secret_env_name[path], valueFrom = aws_secretsmanager_secret.external[path].arn } if can(regex("^(termii|twilio)/", path))]
    frontend      = []
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each = local.services

  family                   = "${local.name_prefix}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task[each.key].arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${aws_ecr_repository.service[each.key].repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = each.value.port
          hostPort      = each.value.port
          protocol      = "tcp"
        }
      ]

      environment = local.service_env[each.key]
      secrets     = local.service_secrets[each.key]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = each.key
        }
      }

      # Container-level health check — independent of the ALB health check.
      # Frontend doesn't expose a /health endpoint in dev, so we use a
      # simple TCP probe for it.
      healthCheck = each.key == "frontend" ? {
        # node fetch against 127.0.0.1, NOT curl/wget/localhost: the image is
        # node:22-alpine (no curl), and alpine resolves `localhost` to ::1
        # first while the Next standalone server binds IPv4 0.0.0.0 — so a
        # localhost probe is refused even though the app is healthy (the ALB,
        # connecting via the ENI IPv4, was serving fine the whole time).
        command     = ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:${each.value.port}/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
        } : {
        command     = ["CMD-SHELL", "curl -f http://localhost:${each.value.port}${each.value.health_path} || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name    = "${local.name_prefix}-${each.key}-task"
    Service = each.key
  }
}

# ─── Services ──────────────────────────────────────────────────────────

resource "aws_ecs_service" "service" {
  for_each = local.services

  name            = "${local.name_prefix}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.service[each.key].arn
  desired_count   = var.ecs_min_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.service[each.key].arn
    container_name   = each.key
    container_port   = each.value.port
  }

  # Rolling deploys — keep at least the min running, scale up briefly.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true # auto-rollback if the new task can't start
  }

  # Ignore desired_count after creation — autoscaling owns it.
  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [
    aws_lb_listener.http,
    aws_lb_listener.https,
  ]

  tags = {
    Name    = "${local.name_prefix}-${each.key}-svc"
    Service = each.key
  }
}

# ─── Autoscaling (CPU target tracking) ────────────────────────────────

resource "aws_appautoscaling_target" "service" {
  for_each = local.services

  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.service[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.ecs_min_count
  max_capacity       = var.ecs_max_count
}

resource "aws_appautoscaling_policy" "service_cpu" {
  for_each = local.services

  name               = "${local.name_prefix}-${each.key}-cpu-tt"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.service[each.key].service_namespace
  resource_id        = aws_appautoscaling_target.service[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.service[each.key].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = var.ecs_target_cpu_percent
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
