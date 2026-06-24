# EconomicBridge — VPC + subnets + routing.
#
# Layout:
#   VPC 10.40.0.0/16
#     Public subnets   10.40.0.0/20, 10.40.16.0/20  (one per AZ)
#       -> Internet gateway (direct internet egress)
#       -> hosts: ALB, NAT gateway
#     Private subnets  10.40.16.0/20, 10.40.32.0/20  (one per AZ)
#       -> NAT gateway (egress only; no inbound from internet)
#       -> hosts: ECS Fargate tasks, RDS, ElastiCache
#
# Why NAT gateway (~$32/mo) instead of NAT instance (~$5/mo):
#   - Managed, HA within an AZ
#   - No security patching
#   - 5x the throughput
# `single_nat_gateway = true` shares one NAT across all private subnets.
# Acceptable for staging; production should set false (one NAT per AZ).

# ─── VPC ────────────────────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

# ─── Internet gateway (public subnet egress) ────────────────────────────

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

# ─── Public subnets (one per AZ) ────────────────────────────────────────

resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

# ─── Private subnets (one per AZ) ───────────────────────────────────────

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${local.azs[count.index]}"
    Tier = "private"
  }
}

# ─── NAT gateways ───────────────────────────────────────────────────────
# Single NAT for staging, one-per-AZ for production. Driven by
# var.single_nat_gateway. Each NAT needs its own Elastic IP.

# NAT count: 0 when use_nat_gateway=false (budget mode — tasks egress via the
# IGW from public subnets instead), else 1 (single) or one-per-AZ.
locals {
  nat_count = var.use_nat_gateway ? (var.single_nat_gateway ? 1 : var.az_count) : 0
}

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-eip-${count.index}"
  }

  # The IGW must exist before EIPs can be associated. Explicit dependency
  # because aws_eip doesn't reference the IGW directly.
  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${local.name_prefix}-nat-${count.index}"
  }

  depends_on = [aws_internet_gateway.main]
}

# ─── Route tables ───────────────────────────────────────────────────────

# Public route table — one shared across all public subnets, default route
# points to the IGW.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-rt-public"
  }
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route tables — one per AZ when multi-NAT, one shared when single-NAT.
# The default (0.0.0.0/0 → NAT) route is a separate resource so it can be
# omitted entirely in budget mode (use_nat_gateway=false), where the private
# subnets carry only RDS/Redis (which need no internet egress).
resource "aws_route_table" "private" {
  count  = var.single_nat_gateway ? 1 : var.az_count
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-rt-private-${count.index}"
  }
}

resource "aws_route" "private_nat" {
  count                  = local.nat_count
  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[count.index].id
}

resource "aws_route_table_association" "private" {
  count     = var.az_count
  subnet_id = aws_subnet.private[count.index].id
  # If single NAT, all private subnets share index 0; otherwise pair by AZ index.
  route_table_id = aws_route_table.private[var.single_nat_gateway ? 0 : count.index].id
}

# ─── VPC endpoints (cost optimisation) ─────────────────────────────────
# S3 gateway endpoint costs nothing and keeps S3 traffic off the NAT
# (saves $0.045/GB on the NAT data-processing charge).

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  # Private route tables always; add the public one too so tasks running in
  # public subnets (budget mode) also reach S3 over the free gateway endpoint.
  route_table_ids = concat(aws_route_table.private[*].id, [aws_route_table.public.id])

  tags = {
    Name = "${local.name_prefix}-vpce-s3"
  }
}
