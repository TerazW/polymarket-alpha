# =============================================================================
# Market Sensemaking - Production Environment Configuration
# =============================================================================

# General
environment  = "production"
project_name = "market-sensemaking"
aws_region   = "us-east-1"

# Domain
domain_name   = "marketsensemaking.com"
api_subdomain = "api"

# Database (production-grade)
db_instance_class        = "db.t3.small"
db_allocated_storage     = 50
db_backup_retention_days = 14

# Redis
redis_node_type       = "cache.t3.micro"
redis_num_cache_nodes = 1

# ECS Resources
ecs_api_cpu           = 512
ecs_api_memory        = 1024
ecs_api_desired_count = 2

ecs_collector_cpu    = 256
ecs_collector_memory = 512

ecs_reactor_cpu    = 512
ecs_reactor_memory = 1024

ecs_tiler_cpu    = 512
ecs_tiler_memory = 1024

# Monitoring
log_retention_days = 90
alarm_email        = ""  # Set your email for alerts
