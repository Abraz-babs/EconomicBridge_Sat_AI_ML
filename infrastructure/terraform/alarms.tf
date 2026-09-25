# EconomicBridge — CloudWatch alarms.
#
# Lean alarm set for staging: enough to catch real problems, not so noisy
# that ops fatigue sets in. SNS topic is optional — set
# var.alarm_email to an address to receive notifications, or wire it up
# to PagerDuty / Slack later.

# ─── SNS topic for alarm fan-out ──────────────────────────────────────

resource "aws_sns_topic" "alarms" {
  name = "${local.name_prefix}-alarms"

  tags = {
    Name = "${local.name_prefix}-alarms"
  }
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ─── ALB alarms ────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx"
  alarm_description   = "ALB returning > 5 5xx errors per minute"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  alarm_name          = "${local.name_prefix}-target-5xx"
  alarm_description   = "Backend tasks returning > 10 5xx errors per minute"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

# ─── ECS service CPU alarms ────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  for_each = local.services

  alarm_name          = "${local.name_prefix}-${each.key}-cpu-high"
  alarm_description   = "${each.key} sustained CPU > 85%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.service[each.key].name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

# ─── RDS alarms ────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${local.name_prefix}-rds-cpu-high"
  alarm_description   = "RDS sustained CPU > 80%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  # .identifier, not .id: in AWS provider v5 `id` is the resource ID
  # (db-XXXX), which CloudWatch never reports under — the alarm sat at
  # INSUFFICIENT_DATA from creation until 2026-09-25.
  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "${local.name_prefix}-rds-storage-low"
  alarm_description   = "RDS free storage below 2GB"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 2 * 1024 * 1024 * 1024 # 2 GB in bytes

  # .identifier, not .id: in AWS provider v5 `id` is the resource ID
  # (db-XXXX), which CloudWatch never reports under — the alarm sat at
  # INSUFFICIENT_DATA from creation until 2026-09-25.
  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

# ─── Redis alarms ──────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "redis_cpu_high" {
  alarm_name          = "${local.name_prefix}-redis-cpu-high"
  alarm_description   = "Redis CPU > 80%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "EngineCPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  # ElastiCache publishes EngineCPUUtilization per NODE (CacheClusterId,
  # e.g. <group>-001), not per replication group — the group dimension
  # never received data.
  dimensions = {
    CacheClusterId = sort(tolist(aws_elasticache_replication_group.main.member_clusters))[0]
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}
