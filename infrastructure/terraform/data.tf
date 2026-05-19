# EconomicBridge — data sources (read-only AWS lookups).

# Current account ID — used in ECR / Secrets Manager ARNs.
data "aws_caller_identity" "current" {}

# Region we're deployed into — used in log group ARNs etc.
data "aws_region" "current" {}

# Available AZs in the current region. We slice this in locals.tf to pick
# the first var.az_count.
data "aws_availability_zones" "available" {
  state = "available"
}
