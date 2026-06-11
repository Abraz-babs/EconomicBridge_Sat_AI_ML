# EconomicBridge — Application Load Balancer.
#
# One ALB fronts all 5 microservices. Path-based routing fans out to the
# right target group:
#
#   /api/v1/*       → api          (port 8000)
#   /ingestion/*    → ingestion    (port 8001)  — internal but routable for debug
#   /ml/*           → ml           (port 8002)  — internal
#   /notifications/*→ notifications(port 8003)
#   /*              → frontend     (port 3000)  — catch-all, lowest priority
#
# HTTPS is terminated at the ALB. If var.acm_certificate_arn is empty, we
# fall back to HTTP-only (staging only — do NOT use in production).

# ─── ALB ───────────────────────────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = var.environment == "production"
  # 300s: big report PDF/CSV exports and slower admin operations were getting
  # cut by the 60s default (manual job triggers also 504'd before they became
  # background tasks).
  idle_timeout               = 300
  drop_invalid_header_fields = true # security: reject malformed Host header etc.

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

# ─── Target groups (one per service, driven by locals.services) ────────

resource "aws_lb_target_group" "service" {
  for_each = local.services

  # ALB target-group names are capped at 32 chars, so use a short
  # `eb-<env>-<service>` form instead of the full name_prefix
  # (`economicbridge-staging-notifications-tg` would be 39 chars).
  name        = "eb-${var.environment}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # Fargate tasks register by IP, not instance

  health_check {
    enabled             = true
    path                = each.value.health_path
    protocol            = "HTTP"
    matcher             = "200-299"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Faster deregistration in non-prod to speed up deploy churn.
  deregistration_delay = var.environment == "production" ? 60 : 15

  # Stickiness off — these services are stateless.
  stickiness {
    type    = "lb_cookie"
    enabled = false
  }

  tags = {
    Name    = "${local.name_prefix}-${each.key}-tg"
    Service = each.key
  }

  lifecycle {
    create_before_destroy = true # rename-safe
  }
}

# ─── HTTP listener ─────────────────────────────────────────────────────
# If we have an ACM cert: redirect 80 → 443.
# If we don't (staging-only fallback): serve HTTP directly with the
# frontend as the default action.

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.acm_certificate_arn != "" ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = var.acm_certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    target_group_arn = var.acm_certificate_arn != "" ? null : aws_lb_target_group.service["frontend"].arn
  }
}

# ─── HTTPS listener (only if cert provided) ───────────────────────────

resource "aws_lb_listener" "https" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06" # TLS 1.2+ only
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service["frontend"].arn
  }
}

# ─── Listener rules (path-based routing) ──────────────────────────────
# We attach rules to whichever listener exists (HTTPS if cert, else HTTP).
# `frontend` is the default action above so we skip its rule.

locals {
  active_listener_arn = var.acm_certificate_arn != "" ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

resource "aws_lb_listener_rule" "service" {
  for_each = { for k, v in local.services : k => v if k != "frontend" }

  listener_arn = local.active_listener_arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service[each.key].arn
  }

  condition {
    path_pattern {
      values = [each.value.path_pattern]
    }
  }
}
