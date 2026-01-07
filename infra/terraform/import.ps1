# =============================================================================
# Market Sensemaking - Terraform Import Script (PowerShell)
# =============================================================================
# Run this script from the terraform directory:
#   cd C:\Projects\market-sensemaking\infra\terraform
#   .\import.ps1
# =============================================================================

$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Importing existing AWS resources into Terraform state" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ECR Repositories - using escaped double quotes
Write-Host "[1/16] ECR api..." -ForegroundColor Yellow
terraform import "aws_ecr_repository.services[\`"api\`"]" "market-sensemaking/api"

Write-Host "[2/16] ECR collector..." -ForegroundColor Yellow
terraform import "aws_ecr_repository.services[\`"collector\`"]" "market-sensemaking/collector"

Write-Host "[3/16] ECR reactor..." -ForegroundColor Yellow
terraform import "aws_ecr_repository.services[\`"reactor\`"]" "market-sensemaking/reactor"

Write-Host "[4/16] ECR tile-worker..." -ForegroundColor Yellow
terraform import "aws_ecr_repository.services[\`"tile-worker\`"]" "market-sensemaking/tile-worker"

# CloudWatch Log Groups - using escaped double quotes
Write-Host "[5/16] CloudWatch api..." -ForegroundColor Yellow
terraform import "aws_cloudwatch_log_group.ecs[\`"api\`"]" "/ecs/market-sensemaking/api"

Write-Host "[6/16] CloudWatch collector..." -ForegroundColor Yellow
terraform import "aws_cloudwatch_log_group.ecs[\`"collector\`"]" "/ecs/market-sensemaking/collector"

Write-Host "[7/16] CloudWatch reactor..." -ForegroundColor Yellow
terraform import "aws_cloudwatch_log_group.ecs[\`"reactor\`"]" "/ecs/market-sensemaking/reactor"

Write-Host "[8/16] CloudWatch tile-worker..." -ForegroundColor Yellow
terraform import "aws_cloudwatch_log_group.ecs[\`"tile-worker\`"]" "/ecs/market-sensemaking/tile-worker"

# IAM Roles
Write-Host "[9/16] IAM ecs-task-execution..." -ForegroundColor Yellow
terraform import "aws_iam_role.ecs_task_execution" "market-sensemaking-ecs-task-execution-role"

Write-Host "[10/16] IAM ecs-task..." -ForegroundColor Yellow
terraform import "aws_iam_role.ecs_task" "market-sensemaking-ecs-task-role"

Write-Host "[11/16] IAM rds-monitoring..." -ForegroundColor Yellow
terraform import "aws_iam_role.rds_monitoring" "market-sensemaking-rds-monitoring-role"

# Database Resources
Write-Host "[12/16] DB subnet group..." -ForegroundColor Yellow
terraform import "aws_db_subnet_group.main" "market-sensemaking-db-subnet-group"

Write-Host "[13/16] DB parameter group..." -ForegroundColor Yellow
terraform import "aws_db_parameter_group.postgres" "market-sensemaking-pg15-params"

# ElastiCache Resources
Write-Host "[14/16] ElastiCache subnet group..." -ForegroundColor Yellow
terraform import "aws_elasticache_subnet_group.main" "market-sensemaking-redis-subnet-group"

Write-Host "[15/16] ElastiCache parameter group..." -ForegroundColor Yellow
terraform import "aws_elasticache_parameter_group.redis" "market-sensemaking-redis-params"

# S3 Bucket
Write-Host "[16/16] S3 bucket..." -ForegroundColor Yellow
terraform import "aws_s3_bucket.alb_logs" "market-sensemaking-alb-logs-821482074659"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Import process completed!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run: terraform plan" -ForegroundColor White
Write-Host "  2. Review the changes" -ForegroundColor White
Write-Host "  3. Run: terraform apply" -ForegroundColor White
Write-Host ""
