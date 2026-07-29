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

variable "use_nat_gateway" {
  description = <<-EOT
    Provision a NAT gateway (~$33/mo) for private-subnet egress. When false
    (budget staging), ECS tasks run in PUBLIC subnets with a public IP and
    egress straight through the internet gateway (free) — the task security
    group still only allows inbound from the ALB, so this does NOT expose the
    tasks. RDS/Redis stay private. Set true for production.
  EOT
  type        = bool
  default     = true
}

variable "parked_services" {
  description = <<-EOT
    Services to "park" at 0 tasks to save cost (no autoscaling, desired_count
    0). The dashboard reads predictions from the database via the api, so
    parking on-demand services like 'ml' keeps every page working — only LIVE
    inference (e.g. uploading a new leaf to CropGuard) needs the service up.
    Bring one back for a demo with:
      aws ecs update-service --cluster <cluster> --service <svc> --desired-count 1
    (the manual count sticks — Terraform ignores desired_count changes.)
  EOT
  type        = list(string)
  default     = []
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
  description = "Days to retain automated backups. 7 for staging, 30 for production. NEVER lower this to satisfy a plan diff — check what the instance is actually set to first; an apply silently shortens the recovery window."
  type        = number
  default     = 7

  validation {
    # 1 was pinned here for months by a free-tier restriction that no longer
    # applies. The account plan was upgraded and RDS moved to 7, but the input
    # stayed at 1, so every plan quietly proposed cutting a week of backups to
    # a day. Anything below 7 now has to be typed deliberately.
    condition     = var.rds_backup_retention_days >= 7
    error_message = "Backup retention below 7 days shortens the recovery window. If a plan restriction genuinely forces it, remove this validation in the same commit that explains why."
  }
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
  # DANGER, and not hypothetical — this exact value was left empty for weeks
  # after economicbridge.org went live on HTTPS.
  #
  # alb.tf keys THREE things off this one string: whether port 80 redirects to
  # 443 or serves traffic directly, whether the 443 listener exists at all, and
  # which listener the path rules attach to. Empty against an environment that
  # is already serving HTTPS therefore does not mean "leave TLS alone" — it
  # means "tear the redirect down and move the routing to port 80".
  #
  # Empty is correct ONLY for a brand-new environment with no certificate yet.
  # If the ALB is already terminating TLS, set this before running plan, and
  # read the plan for aws_lb_listener.http before applying it.
  description = "ARN of the ACM cert for HTTPS. Empty provisions an HTTP-only ALB — safe on a NEW environment, DESTRUCTIVE on one already serving HTTPS (it removes the 80->443 redirect)."
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

variable "email_backend" {
  description = "Override email backend: 'resend' | 'ses' | 'console'. Empty = auto (ses if ses_sender_email set, else console). Set 'resend' once a domain is verified in Resend and the resend/api_key secret is populated."
  type        = string
  default     = ""
}

variable "email_from" {
  description = "From address for outbound email (e.g. no-reply@yourdomain). Empty falls back to ses_sender_email."
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

variable "sms_sns_enabled" {
  description = "Enable outbound SMS via Amazon SNS on the notifications service (sets SNS_ENABLED=true). NOTE: SNS SMS also requires moving the AWS account out of the SMS sandbox and registering the destination-country sender ID (e.g. Nigeria) in the console — a one-time manual step, not Terraform."
  type        = bool
  default     = false
}

variable "sms_sns_sender_id" {
  description = "Alphanumeric SNS SMS sender ID shown on the handset. Must be registered with AWS for the destination countries."
  type        = string
  default     = "EconBridge"
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

variable "enable_feed_health_watchdog" {
  description = "Provision the daily EventBridge schedule that runs scripts.check_feed_health on the api task and emails the super-admin on findings. Depends on the reports_scheduler IAM role, so enable_scheduled_reports must also be true."
  type        = bool
  default     = true
}

variable "feed_health_schedule" {
  description = "EventBridge Scheduler expression for the feed-health watchdog. Daily is right: it compares each feed against a multi-day staleness budget and emails only on findings."
  type        = string
  default     = "cron(30 9 * * ? *)"
}

variable "primary_domain" {
  description = "Public hostname clients use. The port-80 listener redirects to it by name (the old-link reroute), so a request to the raw ALB DNS lands on the real domain."
  type        = string
  default     = "economicbridge.org"
}
