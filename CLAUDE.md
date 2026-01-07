# Market Sensemaking - Claude 開發筆記

## 分支
- 開發分支：`claude/initial-setup-xsnPm`

## AWS 部署狀態

### 帳戶信息
- AWS Account ID: `821482074659`
- Region: `us-east-1`
- Domain: `marketsensemaking.com` (Cloudflare DNS)

### 已完成的基礎設施 (Terraform)
- VPC + 子網 (公有/私有)
- ECS Fargate 集群：`market-sensemaking-cluster`
- RDS PostgreSQL 數據庫
- ElastiCache Redis
- Application Load Balancer (ALB)
- ACM SSL 證書 (已驗證)
- VPC Endpoints (ECR, S3, CloudWatch Logs, Secrets Manager)
- 4 個 ECR 倉庫

### ECR 倉庫名稱 (重要!)
需要確認實際名稱，運行：
```bash
aws ecr describe-repositories --region us-east-1
```

### ECS 服務
- market-sensemaking-api
- market-sensemaking-collector
- market-sensemaking-reactor
- market-sensemaking-tile-worker

## 當前問題

### 數據庫連接錯誤 (已修復代碼，待部署)
容器嘗試連接 `127.0.0.1:5433` 而不是 RDS。

**已修復的文件** (使用環境變量讀取 DB 配置):
- backend/api/main.py
- backend/api/routes/v1.py
- backend/api/routes/events.py
- backend/api/routes/collector.py
- backend/collector/main.py
- backend/heatmap/precompute.py
- backend/heatmap/tile_generator.py
- backend/jobs/verify_bundles.py
- backend/reactor/service.py

### 待完成
1. ~~確認 ECR 倉庫實際名稱~~ ✅
2. ~~重新構建 Docker 鏡像~~ ✅
3. ~~推送到 ECR~~ ✅
4. ~~更新 ECS 服務~~ ✅
5. 運行數據庫遷移 ⬅️ **當前步驟**

## 數據庫遷移

### 問題
RDS 數據庫沒有創建表結構，collector 報錯：`relation "book_bins" does not exist`

### 解決方案
使用 `init_postgresql.sql` (標準 PostgreSQL 版本，不需要 TimescaleDB)

### 遷移步驟 (在 Windows PowerShell 運行)

```powershell
# 1. 登入 ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "821482074659.dkr.ecr.us-east-1.amazonaws.com"

# 2. 創建遷移倉庫 (如果不存在)
aws ecr create-repository --repository-name market-sensemaking-migration --region us-east-1

# 3. 構建遷移鏡像 (在 C:\Projects\market-sensemaking 目錄下)
docker build -t market-sensemaking-migration -f infra/Dockerfile.migrate .

# 4. 標記並推送
docker tag market-sensemaking-migration:latest 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking-migration:latest
docker push 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking-migration:latest

# 5. 應用 Terraform 更新 (創建遷移任務定義)
cd infra/terraform
terraform init
terraform apply -target=aws_ecr_repository.migration -target=aws_ecs_task_definition.migration -target=aws_cloudwatch_log_group.migration

# 6. 運行遷移任務
aws ecs run-task `
  --cluster market-sensemaking-cluster `
  --task-definition market-sensemaking-migration `
  --launch-type FARGATE `
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}" `
  --region us-east-1

# 7. 查看遷移日志
aws logs tail /ecs/market-sensemaking/migration --follow --region us-east-1
```

### 獲取子網和安全組 ID
```powershell
# 獲取私有子網 ID
aws ec2 describe-subnets --filters "Name=tag:Name,Values=*market-sensemaking*private*" --query "Subnets[].SubnetId" --region us-east-1

# 獲取 ECS 任務安全組 ID
aws ec2 describe-security-groups --filters "Name=tag:Name,Values=*market-sensemaking*ecs*" --query "SecurityGroups[].GroupId" --region us-east-1
```

## 本地項目路徑 (Windows)
```
C:\Projects\market-sensemaking
```

## Dockerfile 位置
```
infra/Dockerfile.api
infra/Dockerfile.collector
infra/Dockerfile.reactor
infra/Dockerfile.tile_worker
```

## 構建命令模板
```powershell
# 1. 登入 ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "821482074659.dkr.ecr.us-east-1.amazonaws.com"

# 2. 先查詢 ECR 倉庫名稱
aws ecr describe-repositories --region us-east-1 --query "repositories[].repositoryName"

# 3. 構建 (在 C:\Projects\market-sensemaking 目錄下)
docker build -t "IMAGE_NAME" -f "infra/Dockerfile.api" .

# 4. 標記
docker tag "IMAGE_NAME" "821482074659.dkr.ecr.us-east-1.amazonaws.com/REPO_NAME:latest"

# 5. 推送
docker push "821482074659.dkr.ecr.us-east-1.amazonaws.com/REPO_NAME:latest"

# 6. 更新 ECS
aws ecs update-service --cluster market-sensemaking-cluster --service SERVICE_NAME --force-new-deployment --region us-east-1
```

## Terraform 文件位置
```
infra/terraform/
```
