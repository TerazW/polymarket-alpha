# =============================================================================
# Market Sensemaking - Database Migration Task
# =============================================================================
# One-time ECS task to initialize database schema

# -----------------------------------------------------------------------------
# ECR Repository for Migration Image
# -----------------------------------------------------------------------------

resource "aws_ecr_repository" "migration" {
  name                 = "${var.project_name}-migration"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-migration"
  }
}

# -----------------------------------------------------------------------------
# Migration Task Definition
# -----------------------------------------------------------------------------

resource "aws_ecs_task_definition" "migration" {
  family                   = "${var.project_name}-migration"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "migration"
      image = "${aws_ecr_repository.migration.repository_url}:latest"

      environment = [
        { name = "DB_HOST", value = aws_db_instance.main.address },
        { name = "DB_PORT", value = "5432" },
        { name = "DB_NAME", value = var.db_name },
      ]

      secrets = [
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
          awslogs-group         = "/ecs/${var.project_name}/migration"
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
          awslogs-create-group  = "true"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name = "${var.project_name}-migration-task"
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group for Migration
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/ecs/${var.project_name}/migration"
  retention_in_days = 7

  tags = {
    Name    = "${var.project_name}-migration-logs"
    Service = "migration"
  }
}
