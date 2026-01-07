# =============================================================================
# Market Sensemaking - Database Migration Script
# =============================================================================
# Run this script from C:\Projects\market-sensemaking directory
# PowerShell: .\scripts\run_migration.ps1

$ErrorActionPreference = "Stop"

# Configuration
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT = "821482074659"
$ECR_REPO = "$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"
$CLUSTER_NAME = "market-sensemaking-cluster"

Write-Host "=" * 60
Write-Host "  Market Sensemaking - Database Migration"
Write-Host "=" * 60
Write-Host ""

# Step 1: Login to ECR
Write-Host "[1/6] Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPO
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to login to ECR"
    exit 1
}
Write-Host "OK: ECR login successful"
Write-Host ""

# Step 2: Create migration repository if not exists
Write-Host "[2/6] Creating migration repository..."
try {
    aws ecr create-repository --repository-name market-sensemaking-migration --region $AWS_REGION 2>$null
    Write-Host "OK: Repository created"
} catch {
    Write-Host "OK: Repository already exists"
}
Write-Host ""

# Step 3: Build migration image
Write-Host "[3/6] Building migration image..."
docker build -t market-sensemaking-migration -f infra/Dockerfile.migrate .
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to build image"
    exit 1
}
Write-Host "OK: Image built"
Write-Host ""

# Step 4: Tag and push
Write-Host "[4/6] Pushing image to ECR..."
docker tag market-sensemaking-migration:latest "$ECR_REPO/market-sensemaking-migration:latest"
docker push "$ECR_REPO/market-sensemaking-migration:latest"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to push image"
    exit 1
}
Write-Host "OK: Image pushed"
Write-Host ""

# Step 5: Get network configuration from existing service
Write-Host "[5/6] Getting network configuration..."

# Get subnets from existing service
$SERVICE_CONFIG = aws ecs describe-services `
    --cluster $CLUSTER_NAME `
    --services market-sensemaking-collector `
    --region $AWS_REGION `
    --query "services[0].networkConfiguration.awsvpcConfiguration" `
    --output json | ConvertFrom-Json

$SUBNETS = $SERVICE_CONFIG.subnets -join ","
$SECURITY_GROUPS = $SERVICE_CONFIG.securityGroups -join ","

Write-Host "Subnets: $SUBNETS"
Write-Host "Security Groups: $SECURITY_GROUPS"
Write-Host ""

# Step 6: Get database credentials from Secrets Manager
Write-Host "[6/6] Getting database credentials..."

# Get the secret ARN
$SECRET_ARN = aws secretsmanager list-secrets `
    --region $AWS_REGION `
    --filter Key=name,Values=market-sensemaking `
    --query "SecretList[0].ARN" `
    --output text

# Get secret values
$SECRET_VALUE = aws secretsmanager get-secret-value `
    --secret-id $SECRET_ARN `
    --region $AWS_REGION `
    --query "SecretString" `
    --output text | ConvertFrom-Json

$DB_HOST = $SECRET_VALUE.host
$DB_USER = $SECRET_VALUE.username
$DB_PASSWORD = $SECRET_VALUE.password
$DB_NAME = $SECRET_VALUE.dbname

Write-Host "DB Host: $DB_HOST"
Write-Host "DB Name: $DB_NAME"
Write-Host ""

# Step 7: Register task definition
Write-Host "[7/8] Registering task definition..."

$TASK_DEF = @"
{
  "family": "market-sensemaking-migration",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT}:role/market-sensemaking-ecs-task-execution-role",
  "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT}:role/market-sensemaking-ecs-task-role",
  "containerDefinitions": [
    {
      "name": "migration",
      "image": "${ECR_REPO}/market-sensemaking-migration:latest",
      "essential": true,
      "environment": [
        {"name": "DB_HOST", "value": "${DB_HOST}"},
        {"name": "DB_PORT", "value": "5432"},
        {"name": "DB_NAME", "value": "${DB_NAME}"},
        {"name": "DB_USER", "value": "${DB_USER}"},
        {"name": "DB_PASSWORD", "value": "${DB_PASSWORD}"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/market-sensemaking/migration",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
"@

$TASK_DEF | Out-File -Encoding utf8 -FilePath "migration-task-def.json"

aws ecs register-task-definition `
    --cli-input-json file://migration-task-def.json `
    --region $AWS_REGION | Out-Null

Remove-Item -Path "migration-task-def.json" -Force

Write-Host "OK: Task definition registered"
Write-Host ""

# Step 8: Run migration task
Write-Host "[8/8] Running migration task..."

$TASK_RESULT = aws ecs run-task `
    --cluster $CLUSTER_NAME `
    --task-definition market-sensemaking-migration `
    --launch-type FARGATE `
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUPS],assignPublicIp=DISABLED}" `
    --region $AWS_REGION `
    --query "tasks[0].taskArn" `
    --output text

Write-Host "Task started: $TASK_RESULT"
Write-Host ""

# Wait for task to complete
Write-Host "Waiting for migration to complete..."
$TASK_ID = $TASK_RESULT.Split("/")[-1]

do {
    Start-Sleep -Seconds 5
    $STATUS = aws ecs describe-tasks `
        --cluster $CLUSTER_NAME `
        --tasks $TASK_RESULT `
        --region $AWS_REGION `
        --query "tasks[0].lastStatus" `
        --output text
    Write-Host "Status: $STATUS"
} while ($STATUS -ne "STOPPED")

# Check exit code
$EXIT_CODE = aws ecs describe-tasks `
    --cluster $CLUSTER_NAME `
    --tasks $TASK_RESULT `
    --region $AWS_REGION `
    --query "tasks[0].containers[0].exitCode" `
    --output text

Write-Host ""
if ($EXIT_CODE -eq "0") {
    Write-Host "=" * 60
    Write-Host "  Migration completed successfully!"
    Write-Host "=" * 60
    Write-Host ""
    Write-Host "Now restart the collector service:"
    Write-Host "  aws ecs update-service --cluster $CLUSTER_NAME --service market-sensemaking-collector --force-new-deployment --region $AWS_REGION"
} else {
    Write-Host "=" * 60
    Write-Host "  Migration FAILED (exit code: $EXIT_CODE)"
    Write-Host "=" * 60
    Write-Host ""
    Write-Host "Check logs with:"
    Write-Host "  aws logs tail /ecs/market-sensemaking/migration --region $AWS_REGION"
}
