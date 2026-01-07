# =============================================================================
# Market Sensemaking - Input Variables
# =============================================================================

# -----------------------------------------------------------------------------
# General
# -----------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (staging, production)"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "market-sensemaking"
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

# -----------------------------------------------------------------------------
# Database (RDS) - Legacy, kept for reference
# -----------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "market_sensemaking"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "msadmin"
}

variable "db_backup_retention_days" {
  description = "Number of days to retain backups"
  type        = number
  default     = 7
}

# -----------------------------------------------------------------------------
# TimescaleDB Cloud (Primary Database)
# -----------------------------------------------------------------------------

variable "use_timescaledb_cloud" {
  description = "Use TimescaleDB Cloud instead of RDS"
  type        = bool
  default     = true
}

variable "timescaledb_host" {
  description = "TimescaleDB Cloud host"
  type        = string
  default     = ""  # Set via terraform.tfvars or environment
}

variable "timescaledb_port" {
  description = "TimescaleDB Cloud port"
  type        = string
  default     = "5432"
}

variable "timescaledb_name" {
  description = "TimescaleDB database name"
  type        = string
  default     = "tsdb"
}

variable "timescaledb_user" {
  description = "TimescaleDB username"
  type        = string
  default     = "tsdbadmin"
}

variable "timescaledb_password" {
  description = "TimescaleDB password"
  type        = string
  sensitive   = true
  default     = ""  # Set via terraform.tfvars or environment
}

# -----------------------------------------------------------------------------
# Redis (ElastiCache)
# -----------------------------------------------------------------------------

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_cache_nodes" {
  description = "Number of cache nodes"
  type        = number
  default     = 1
}

# -----------------------------------------------------------------------------
# ECS
# -----------------------------------------------------------------------------

variable "ecs_api_cpu" {
  description = "CPU units for API service (1024 = 1 vCPU)"
  type        = number
  default     = 256
}

variable "ecs_api_memory" {
  description = "Memory for API service in MB"
  type        = number
  default     = 512
}

variable "ecs_api_desired_count" {
  description = "Desired number of API tasks"
  type        = number
  default     = 2
}

variable "ecs_collector_cpu" {
  description = "CPU units for Collector service"
  type        = number
  default     = 256
}

variable "ecs_collector_memory" {
  description = "Memory for Collector service in MB"
  type        = number
  default     = 512
}

variable "ecs_reactor_cpu" {
  description = "CPU units for Reactor service"
  type        = number
  default     = 256
}

variable "ecs_reactor_memory" {
  description = "Memory for Reactor service in MB"
  type        = number
  default     = 512
}

variable "ecs_tiler_cpu" {
  description = "CPU units for Tile Worker service"
  type        = number
  default     = 512
}

variable "ecs_tiler_memory" {
  description = "Memory for Tile Worker service in MB"
  type        = number
  default     = 1024
}

# -----------------------------------------------------------------------------
# Domain & SSL
# -----------------------------------------------------------------------------

variable "domain_name" {
  description = "Primary domain name"
  type        = string
  default     = "marketsensemaking.com"
}

variable "api_subdomain" {
  description = "API subdomain"
  type        = string
  default     = "api"
}

# -----------------------------------------------------------------------------
# Monitoring
# -----------------------------------------------------------------------------

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Email for CloudWatch alarms"
  type        = string
  default     = ""
}
