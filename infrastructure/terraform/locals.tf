# EconomicBridge — computed locals.
#
# Anything derived from variables + data sources lives here so the rest of
# the files read like declarative descriptions of intent rather than string
# manipulations.

locals {
  # Naming prefix used on every resource: "economicbridge-staging-..."
  name_prefix = "${var.project_name}-${var.environment}"

  # AZs we actually use (data.aws_availability_zones returns ALL of them
  # in the region; we take the first N).
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # CIDR carve-up: /20 per subnet gives 4096 IPs each, plenty for any
  # imaginable scale. Public subnets in slot 0-1, private in slot 16-17,
  # so they don't collide and remain visually distinct in route tables.
  public_subnet_cidrs  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  private_subnet_cidrs = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 16)]

  # The 5 microservices we're deploying. Per-service config drives:
  #   - ECR repo name
  #   - ECS task definition (CPU/memory, container port)
  #   - ALB target group + listener rule
  # Any service-shape change ripples consistently through everything.
  services = {
    api = {
      port          = 8000
      cpu           = 512
      memory        = 1024
      path_pattern  = "/api/v1/*"
      health_path   = "/api/v1/health"
      priority      = 100
      public        = true
      needs_db      = true
      needs_redis   = true
    }
    ingestion = {
      port          = 8001
      cpu           = 512
      memory        = 1024
      path_pattern  = "/ingestion/*"
      health_path   = "/api/v1/health"
      priority      = 200
      public        = false  # internal-only; called by api / cron
      needs_db      = true
      needs_redis   = true
    }
    ml = {
      port          = 8002
      cpu           = 1024  # sklearn + shap need more CPU
      memory        = 2048
      path_pattern  = "/ml/*"
      health_path   = "/api/v1/health"
      priority      = 300
      public        = false  # internal-only; called by api
      needs_db      = false
      needs_redis   = false
    }
    notifications = {
      port          = 8003
      cpu           = 512
      memory        = 1024
      path_pattern  = "/notifications/*"
      health_path   = "/api/v1/health"
      priority      = 400
      public        = true   # /api/v1/subscribers is open-access for opt-in
      needs_db      = true
      needs_redis   = false
    }
    frontend = {
      port          = 3000
      cpu           = 256
      memory        = 512
      path_pattern  = "/*"      # catch-all — must be lowest priority
      health_path   = "/"
      priority      = 1000
      public        = true
      needs_db      = false
      needs_redis   = false
    }
  }

  # Secrets Manager paths per CLAUDE.md §8. The keys live here so secrets.tf
  # is just a `for_each` over this map. Values populated separately (out of
  # band) — Terraform creates the empty secret and you `aws secretsmanager
  # put-secret-value` later. Never put real values in tfvars.
  secret_paths = [
    "copernicus/client_id",
    "copernicus/client_secret",
    "nasa_firms/api_key",
    "n2yo/api_key",
    "earth_engine/service_account",
    "mapbox/public_token",
    "claude/api_key",
    "termii/api_key",
    "twilio/account_sid",
    "twilio/auth_token",
  ]
}
