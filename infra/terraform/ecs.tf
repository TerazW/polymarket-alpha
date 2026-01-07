# =============================================================================
# Market Sensemaking - ECS Fargate
# =============================================================================

# -----------------------------------------------------------------------------
# ECS Cluster
# -----------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# -----------------------------------------------------------------------------
# IAM Roles
# -----------------------------------------------------------------------------

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "${var.project_name}-ecs-secrets-policy"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.db_credentials.arn
        ]
      }
    ]
  })
}

# ECS Task Role
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task-role"
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Log Groups
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ecs" {
  for_each = toset(["api", "collector", "reactor", "tile-worker"])

  name              = "/ecs/${var.project_name}/${each.key}"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${var.project_name}-${each.key}-logs"
    Service = each.key
  }
}

# -----------------------------------------------------------------------------
# Task Definitions
# -----------------------------------------------------------------------------

# API Service Task Definition
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_api_cpu
  memory                   = var.ecs_api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "api"
      image = "${aws_ecr_repository.services["api"].repository_url}:latest"

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "DB_HOST", value = var.use_timescaledb_cloud ? var.timescaledb_host : aws_db_instance.main.address },
        { name = "DB_PORT", value = var.use_timescaledb_cloud ? var.timescaledb_port : "5432" },
        { name = "DB_NAME", value = var.use_timescaledb_cloud ? var.timescaledb_name : var.db_name },
        { name = "DB_USER", value = var.use_timescaledb_cloud ? var.timescaledb_user : "" },
        { name = "DB_PASSWORD", value = var.use_timescaledb_cloud ? var.timescaledb_password : "" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379" },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "ENVIRONMENT", value = var.environment },
      ]

      secrets = var.use_timescaledb_cloud ? [] : [
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
        },
        {
          name      = "DB_USER"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:username::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["api"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/v1/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-api-task"
  }
}

# Collector Service Task Definition
resource "aws_ecs_task_definition" "collector" {
  family                   = "${var.project_name}-collector"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_collector_cpu
  memory                   = var.ecs_collector_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "collector"
      image = "${aws_ecr_repository.services["collector"].repository_url}:latest"

      environment = [
        { name = "DB_HOST", value = var.use_timescaledb_cloud ? var.timescaledb_host : aws_db_instance.main.address },
        { name = "DB_PORT", value = var.use_timescaledb_cloud ? var.timescaledb_port : "5432" },
        { name = "DB_NAME", value = var.use_timescaledb_cloud ? var.timescaledb_name : var.db_name },
        { name = "DB_USER", value = var.use_timescaledb_cloud ? var.timescaledb_user : "" },
        { name = "DB_PASSWORD", value = var.use_timescaledb_cloud ? var.timescaledb_password : "" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379" },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "POLYMARKET_WS_URL", value = "wss://ws-subscriptions-clob.polymarket.com/ws/market" },
      ]

      secrets = var.use_timescaledb_cloud ? [] : [
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
        },
        {
          name      = "DB_USER"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:username::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["collector"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-collector-task"
  }
}

# Reactor Service Task Definition
resource "aws_ecs_task_definition" "reactor" {
  family                   = "${var.project_name}-reactor"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_reactor_cpu
  memory                   = var.ecs_reactor_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "reactor"
      image = "${aws_ecr_repository.services["reactor"].repository_url}:latest"

      environment = [
        { name = "DB_HOST", value = var.use_timescaledb_cloud ? var.timescaledb_host : aws_db_instance.main.address },
        { name = "DB_PORT", value = var.use_timescaledb_cloud ? var.timescaledb_port : "5432" },
        { name = "DB_NAME", value = var.use_timescaledb_cloud ? var.timescaledb_name : var.db_name },
        { name = "DB_USER", value = var.use_timescaledb_cloud ? var.timescaledb_user : "" },
        { name = "DB_PASSWORD", value = var.use_timescaledb_cloud ? var.timescaledb_password : "" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379" },
        { name = "LOG_LEVEL", value = "INFO" },
      ]

      secrets = var.use_timescaledb_cloud ? [] : [
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
        },
        {
          name      = "DB_USER"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:username::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["reactor"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-reactor-task"
  }
}

# Tile Worker Service Task Definition
resource "aws_ecs_task_definition" "tile_worker" {
  family                   = "${var.project_name}-tile-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_tiler_cpu
  memory                   = var.ecs_tiler_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "tile-worker"
      image = "${aws_ecr_repository.services["tile-worker"].repository_url}:latest"

      environment = [
        { name = "DB_HOST", value = var.use_timescaledb_cloud ? var.timescaledb_host : aws_db_instance.main.address },
        { name = "DB_PORT", value = var.use_timescaledb_cloud ? var.timescaledb_port : "5432" },
        { name = "DB_NAME", value = var.use_timescaledb_cloud ? var.timescaledb_name : var.db_name },
        { name = "DB_USER", value = var.use_timescaledb_cloud ? var.timescaledb_user : "" },
        { name = "DB_PASSWORD", value = var.use_timescaledb_cloud ? var.timescaledb_password : "" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379" },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "TILE_WORKERS", value = "2" },
      ]

      secrets = var.use_timescaledb_cloud ? [] : [
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
        },
        {
          name      = "DB_USER"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:username::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["tile-worker"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-tile-worker-task"
  }
}

# -----------------------------------------------------------------------------
# ECS Services
# -----------------------------------------------------------------------------

# API Service
resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.ecs_api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]

  tags = {
    Name = "${var.project_name}-api-service"
  }
}

# Collector Service
resource "aws_ecs_service" "collector" {
  name            = "${var.project_name}-collector"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.collector.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = "${var.project_name}-collector-service"
  }
}

# Reactor Service
resource "aws_ecs_service" "reactor" {
  name            = "${var.project_name}-reactor"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.reactor.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = "${var.project_name}-reactor-service"
  }
}

# Tile Worker Service
resource "aws_ecs_service" "tile_worker" {
  name            = "${var.project_name}-tile-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.tile_worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = "${var.project_name}-tile-worker-service"
  }
}
