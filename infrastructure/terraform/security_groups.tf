# EconomicBridge — security groups (least-privilege).
#
# Defence in depth: every layer can only talk to the layers it needs to.
# Trust direction:
#
#   Internet -> ALB (443/80)
#               ALB -> ECS tasks (per-service port)
#                      ECS tasks -> RDS (5432) + Redis (6379)
#                      ECS tasks -> any HTTPS upstream (NASA FIRMS, Termii)
#
# No SG allows inbound from 0.0.0.0/0 except the ALB. RDS / Redis are
# private-subnet-only and never reachable from the internet.

# ─── ALB ─────────────────────────────────────────────────────────────────
# Sits in public subnets, accepts 443 from the world (or var.alb_allowed_cidrs).
# Egress to anywhere so it can reach ECS task ports.

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "ALB ingress from the internet, egress to ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from allowed CIDRs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.alb_allowed_cidrs
  }

  ingress {
    description = "HTTP from allowed CIDRs (redirects to 443)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.alb_allowed_cidrs
  }

  egress {
    description = "All outbound to VPC (ALB reaches ECS tasks)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

# ─── ECS tasks ──────────────────────────────────────────────────────────
# One SG shared by all 5 ECS services. Each service exposes its own port,
# so we add an ingress rule per service-port driven by the locals.services map.
# Egress is unrestricted because tasks need to reach NASA FIRMS, Termii, etc.

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name_prefix}-ecs-tasks-sg"
  description = "ECS task ingress from ALB; egress to RDS, Redis, and external APIs"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All outbound (external APIs, RDS, Redis, ECR pulls)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-ecs-tasks-sg"
  }
}

# One ingress rule per service port — created as separate aws_security_group_rule
# resources so adding a service in locals.services automatically opens the port.
resource "aws_security_group_rule" "ecs_from_alb" {
  for_each = local.services

  type                     = "ingress"
  description              = "From ALB to ${each.key} on port ${each.value.port}"
  from_port                = each.value.port
  to_port                  = each.value.port
  protocol                 = "tcp"
  security_group_id        = aws_security_group.ecs_tasks.id
  source_security_group_id = aws_security_group.alb.id
}

# ─── RDS ────────────────────────────────────────────────────────────────
# Only ECS tasks may reach Postgres on 5432. Not the internet, not the ALB.

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS ingress from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  # Egress not strictly needed (RDS doesn't initiate), but allow for clarity
  # and to match the AWS default that would otherwise apply.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

# ─── Redis ──────────────────────────────────────────────────────────────

resource "aws_security_group" "redis" {
  name        = "${local.name_prefix}-redis-sg"
  description = "Redis ingress from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-redis-sg"
  }
}
