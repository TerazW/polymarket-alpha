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
1. 確認 ECR 倉庫實際名稱
2. 重新構建 Docker 鏡像
3. 推送到 ECR
4. 更新 ECS 服務
5. 運行數據庫遷移

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
