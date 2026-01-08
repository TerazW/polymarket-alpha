# =============================================================================
# Market Sensemaking - Staging Environment Configuration
# =============================================================================

# General
environment  = "staging"
project_name = "market-sensemaking-staging"
aws_region   = "us-east-1"

# Domain
domain_name   = "marketsensemaking.com"
api_subdomain = "api-staging"

# Database (cost-optimized)
db_instance_class        = "db.t3.micro"
db_allocated_storage     = 20
db_backup_retention_days = 3

# Redis
redis_node_type       = "cache.t3.micro"
redis_num_cache_nodes = 1

# ECS Resources (minimal for staging)
ecs_api_cpu           = 256
ecs_api_memory        = 512
ecs_api_desired_count = 1

ecs_collector_cpu    = 256
ecs_collector_memory = 512

ecs_reactor_cpu    = 256
ecs_reactor_memory = 512

ecs_tiler_cpu    = 256
ecs_tiler_memory = 512

# Monitoring
log_retention_days = 14
alarm_email        = ""  # Optional for staging
