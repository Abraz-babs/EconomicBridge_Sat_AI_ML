# EconomicBridge — root input variables.
#
# Defaults are staging-optimised (single-AZ, smaller instance sizes, no
# autoscaling). Production overrides via `terraform.tfvars` in a separate
# workspace — see terraform.tfvars.example for the recommended prod values.

# ─── Region + environment ──────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region. Staging = eu-west-1, production = af-south-1."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment slug: 'staging' | 'production' | 'dev'."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production", "dev"], var.environment)
    error_message = "environment must be one of: staging, production, dev."
  }
}

variable "project_name" {
  description = "Short project slug used as a resource-name prefix."
  type        = string
  default     = "economicbridge"
}

# ─── Network ───────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC. /16 gives us 65k IPs across the two AZs."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to span. 2 = Multi-AZ for RDS."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3 (Multi-AZ minimum is 2)."
  }
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway across AZs (cheaper, single point of failure). True for staging, false for production."
  type        = bool
  default     = true
}

# ─── RDS ───────────────────────────────────────────────────────────────

variable "rds_instance_class" {
  description = "RDS instance class. db.t3.small ~$30/mo, db.t3.medium ~$60/mo."
  type        = string
  default     = "db.t3.small"
}

variable "rds_allocated_storage_gb" {
  description = "RDS initial storage in GB. Autoscales up to rds_max_storage_gb."
  type        = number
  default     = 20
}

variable "rds_max_storage_gb" {
  description = "RDS storage upper bound for autoscaling."
  type        = number
  default     = 100
}

variable "rds_multi_az" {
  description = "Run RDS Multi-AZ. CLAUDE.md §3 mandates this for production."
  type        = bool
  default     = true
}

variable "rds_backup_retention_days" {
  description = "Days to retain automated backups. 7 for staging, 30 for production."
  type        = number
  default     = 7
}

variable "rds_deletion_protection" {
  description = "Block `terraform destroy` from deleting the DB. Set to true in production."
  type        = bool
  default     = false
}

# ─── ElastiCache Redis ────────────────────────────────────────────────

variable "redis_node_type" {
  description = "ElastiCache node type. cache.t3.micro ~$11/mo."
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_cache_nodes" {
  description = "Number of Redis replicas. 1 for staging, 2 for production."
  type        = number
  default     = 1
}

# ─── ECS ───────────────────────────────────────────────────────────────

variable "ecs_task_cpu_units" {
  description = "Default Fargate CPU per task (1024 = 1 vCPU). Per-service overrides in locals.tf."
  type        = number
  default     = 512
}

variable "ecs_task_memory_mb" {
  description = "Default Fargate memory per task in MB."
  type        = number
  default     = 1024
}

variable "ecs_min_count" {
  description = "Minimum task count per service. 1 for staging, 2+ for production."
  type        = number
  default     = 1
}

variable "ecs_max_count" {
  description = "Maximum task count per service. Autoscaling ceiling."
  type        = number
  default     = 4
}

variable "ecs_target_cpu_percent" {
  description = "CPU utilisation target for ECS Service Autoscaling."
  type        = number
  default     = 70
}

# ─── ALB / TLS ────────────────────────────────────────────────────────

variable "acm_certificate_arn" {
  description = "ARN of the ACM cert for HTTPS. Leave empty to provision an HTTP-only ALB (staging-only fallback)."
  type        = string
  default     = ""
}

variable "alb_allowed_cidrs" {
  description = "CIDR blocks allowed to hit the ALB on 443. Leave 0.0.0.0/0 for public dashboards."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ─── Container images ─────────────────────────────────────────────────

variable "image_tag" {
  description = "Container image tag deployed to all ECS services. Set by CI/CD to the git SHA."
  type        = string
  default     = "latest"
}

# ─── Auth / onboarding ────────────────────────────────────────────────

variable "ses_sender_email" {
  description = "Verified SES sender for tenant invite/activation emails. Leave empty to fall back to EMAIL_BACKEND=console (link logged, not emailed)."
  type        = string
  default     = ""
}

variable "super_admin_email" {
  description = "Platform operator (super-admin) login email — set as SUPER_ADMIN_EMAIL on the api task; the password is the auth/super_admin_password secret."
  type        = string
  default     = "admin@economicbridge.app"
}

variable "public_app_url" {
  description = "Public dashboard origin for invite links (e.g. https://app.economicbridge.org). Empty → derived from the ALB DNS name."
  type        = string
  default     = ""
}

variable "enable_scheduled_reports" {
  description = "Provision an EventBridge schedule that runs scripts.send_scheduled_reports (emails due report PDFs) on the api task. Needs SES live to actually send."
  type        = bool
  default     = true
}

variable "scheduled_reports_schedule" {
  description = "EventBridge Scheduler expression for the report-emailer (it only sends what's due, so daily is safe)."
  type        = string
  default     = "rate(1 day)"
}

# ─── Observability ────────────────────────────────────────────────────

variable "alarm_email" {
  description = "Email address subscribed to the alarms SNS topic. Leave empty to skip subscription (topic is still created)."
  type        = string
  default     = ""
}
