# EconomicBridge — ElastiCache Redis (single shard, optional replica).
#
# Used by FastAPI for:
#   - JWT refresh token blacklist
#   - Tenant config cache (5-minute TTL)
#   - Celery broker (when ingestion service ships)
#   - Pub/sub channel for alert fan-out
#
# Single shard is fine — our hot dataset is tiny (<1GB). Replicas matter
# only in production (var.redis_num_cache_nodes >= 2 → automatic_failover_enabled).

resource "aws_elasticache_subnet_group" "main" {
  name        = "${local.name_prefix}-redis-subnets"
  description = "Private subnets for ElastiCache Redis"
  subnet_ids  = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-redis-subnets"
  }
}

# Redis 7 parameter group — defaults are fine but we want our own group
# so future tuning doesn't require recreating the cluster.
resource "aws_elasticache_parameter_group" "redis7" {
  name        = "${local.name_prefix}-redis7"
  family      = "redis7"
  description = "Redis 7 parameters for EconomicBridge"

  tags = {
    Name = "${local.name_prefix}-redis7-params"
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "EconomicBridge Redis — cache + pub/sub"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = var.redis_num_cache_nodes
  parameter_group_name = aws_elasticache_parameter_group.redis7.name
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # Failover is automatic if we have >=2 nodes
  automatic_failover_enabled = var.redis_num_cache_nodes >= 2
  multi_az_enabled           = var.redis_num_cache_nodes >= 2

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  snapshot_retention_limit = 7
  snapshot_window          = "01:00-02:00" # UTC, before RDS backups
  maintenance_window       = "sun:04:30-sun:05:30"

  apply_immediately = var.environment != "production"

  tags = {
    Name = "${local.name_prefix}-redis"
  }
}
