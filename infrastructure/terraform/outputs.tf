# EconomicBridge — Terraform outputs.
#
# Things downstream tooling (GitHub Actions, runbooks, the operator's
# terminal) needs to know after `terraform apply`. Sensitive values are
# marked `sensitive = true` so they don't leak into CI logs.

# ─── Network ───────────────────────────────────────────────────────────

output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (host the ALB + NAT)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (host ECS, RDS, Redis)."
  value       = aws_subnet.private[*].id
}

# ─── ALB ───────────────────────────────────────────────────────────────

output "alb_dns_name" {
  description = "ALB DNS name. Point your Route 53 record at this."
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID — needed for Route 53 alias records."
  value       = aws_lb.main.zone_id
}

# ─── ECR ───────────────────────────────────────────────────────────────

output "ecr_repository_urls" {
  description = "Map of service → ECR repo URL. CI/CD pushes images here."
  value       = { for k, v in aws_ecr_repository.service : k => v.repository_url }
}

# ─── ECS ───────────────────────────────────────────────────────────────

output "ecs_cluster_name" {
  description = "ECS Fargate cluster name."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_names" {
  description = "Map of service → ECS service name."
  value       = { for k, v in aws_ecs_service.service : k => v.name }
}

# ─── RDS ───────────────────────────────────────────────────────────────

output "rds_endpoint" {
  description = "RDS endpoint host:port. Use this from inside the VPC."
  value       = aws_db_instance.main.endpoint
}

output "rds_address" {
  description = "RDS host (no port)."
  value       = aws_db_instance.main.address
}

output "rds_db_name" {
  description = "RDS database name."
  value       = aws_db_instance.main.db_name
}

output "rds_password_secret_arn" {
  description = "ARN of the Secrets Manager entry holding the RDS master password."
  value       = aws_secretsmanager_secret.rds_password.arn
}

# ─── Redis ─────────────────────────────────────────────────────────────

output "redis_primary_endpoint" {
  description = "Redis primary endpoint host."
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

# ─── Secrets ───────────────────────────────────────────────────────────

output "external_secret_arns" {
  description = "Map of secret path → ARN. Use `aws secretsmanager put-secret-value` to populate."
  value       = { for k, v in aws_secretsmanager_secret.external : k => v.arn }
}

# ─── Observability ─────────────────────────────────────────────────────

output "alarm_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms. Subscribe additional endpoints with `aws sns subscribe`."
  value       = aws_sns_topic.alarms.arn
}

output "log_group_names" {
  description = "Map of service → CloudWatch log group name."
  value       = { for k, v in aws_cloudwatch_log_group.service : k => v.name }
}

# ─── Account + region (handy for CI) ──────────────────────────────────

output "aws_account_id" {
  description = "Account ID this stack is deployed into."
  value       = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  description = "Region this stack is deployed into."
  value       = data.aws_region.current.name
}
