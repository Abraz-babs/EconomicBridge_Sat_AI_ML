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

  # CIDR carve-up: /24 per subnet (256 IPs each, ample for ECS/RDS).
  # Public subnets in slot 0-1, private in slot 16-17, so they don't collide
  # and remain visually distinct in route tables. NOTE: the extension must be
  # /8 — a /4 extension only yields 16 subnets (0-15) and the private slots
  # at 16+ overflowed it.
  public_subnet_cidrs  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnet_cidrs = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 16)]

  # The 5 microservices we're deploying. Per-service config drives:
  #   - ECR repo name
  #   - ECS task definition (CPU/memory, container port)
  #   - ALB target group + listener rule
  # Any service-shape change ripples consistently through everything.
  services = {
    api = {
      port         = 8000
      cpu          = 512
      memory       = 1024
      path_pattern = "/api/v1/*"
      health_path  = "/api/v1/health"
      priority     = 100
      public       = true
      needs_db     = true
      needs_redis  = true
    }
    ingestion = {
      port         = 8001
      cpu          = 512
      memory       = 1024
      path_pattern = "/ingestion/*"
      health_path  = "/api/v1/health"
      # ALB forwards paths unchanged; the app strips this prefix itself
      # (UrlPrefixStripMiddleware, env URL_PREFIX). api/frontend need none —
      # their patterns match what they natively serve.
      url_prefix  = "/ingestion"
      priority    = 200
      public      = false # internal-only; called by api / cron
      needs_db    = true
      needs_redis = true
    }
    ml = {
      port         = 8002
      cpu          = 1024 # sklearn + shap need more CPU
      memory       = 2048
      path_pattern = "/ml/*"
      health_path  = "/api/v1/health"
      url_prefix   = "/ml"
      priority     = 300
      public       = false # internal-only; called by api
      needs_db     = true  # persists crop predictions (predict_crop routers)
      needs_redis  = false
    }
    notifications = {
      port = 8003
      # Light SMS-dispatch service — 0.25 vCPU / 0.5 GB is plenty (saves ~$9/mo
      # vs 0.5/1). Bump back to 512/1024 if it ever gets CPU-starved.
      cpu          = 256
      memory       = 512
      path_pattern = "/notifications/*"
      health_path  = "/api/v1/health"
      url_prefix   = "/notifications"
      priority     = 400
      public       = true # /api/v1/subscribers is open-access for opt-in
      needs_db     = true
      needs_redis  = false
    }
    frontend = {
      port         = 3000
      cpu          = 256
      memory       = 512
      path_pattern = "/*" # catch-all — must be lowest priority
      health_path  = "/"
      priority     = 1000
      public       = true
      needs_db     = false
      needs_redis  = false
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
    # Added for the live open-data feeds (Skills + Poverty/VIIRS).
    "giga/api_key",
    "earthdata/token",
    # Transactional email via Resend (replaces denied AWS SES). Operator
    # populates; api reads it when EMAIL_BACKEND=resend.
    "resend/api_key",
    # Super-admin bootstrap password — operator populates, read once by the
    # seed_super_admin one-off task (see README). NOT the JWT key (that's
    # Terraform-generated in secrets.tf).
    "auth/super_admin_password",
  ]

  # Secret path → the ENV VAR NAME each service's config actually reads.
  # Most are upper(replace(path,'/','_')), but a few differ from that default
  # and must be pinned or the live feed silently falls back to mock in prod
  # (e.g. the app reads NASA_FIRMS_MAP_KEY, not NASA_FIRMS_API_KEY).
  secret_env_name = {
    "copernicus/client_id"         = "COPERNICUS_CLIENT_ID"
    "copernicus/client_secret"     = "COPERNICUS_CLIENT_SECRET"
    "nasa_firms/api_key"           = "NASA_FIRMS_MAP_KEY"
    "n2yo/api_key"                 = "N2YO_API_KEY"
    "earth_engine/service_account" = "GEE_SERVICE_ACCOUNT"
    "mapbox/public_token"          = "NEXT_PUBLIC_MAPBOX_TOKEN"
    "claude/api_key"               = "ANTHROPIC_API_KEY"
    "termii/api_key"               = "TERMII_API_KEY"
    "twilio/account_sid"           = "TWILIO_ACCOUNT_SID"
    "twilio/auth_token"            = "TWILIO_AUTH_TOKEN"
    "giga/api_key"                 = "GIGA_API_KEY"
    "earthdata/token"              = "EARTHDATA_TOKEN"
    "resend/api_key"               = "RESEND_API_KEY"
    "auth/super_admin_password"    = "SUPER_ADMIN_PASSWORD"
  }
}
