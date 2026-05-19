# EconomicBridge — CloudWatch log groups.
#
# One log group per service. ECS task definitions in ecs.tf reference
# these via the awslogs driver. Retention deliberately short on non-prod
# to keep the bill down; longer in production.

resource "aws_cloudwatch_log_group" "service" {
  for_each = local.services

  name              = "/ecs/${local.name_prefix}/${each.key}"
  retention_in_days = var.environment == "production" ? 90 : 14

  tags = {
    Name    = "${local.name_prefix}-${each.key}-logs"
    Service = each.key
  }
}
