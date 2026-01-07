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

## TimescaleDB Cloud 部署 (方案 A)

### 為什麼用 TimescaleDB Cloud？
- AWS RDS 不支持 TimescaleDB 擴展
- TimescaleDB Cloud 提供完整的時序數據庫功能
- 原始 `init.sql` 架構設計需要 TimescaleDB

### 步驟 1：創建 TimescaleDB Cloud 實例

1. 訪問 https://console.cloud.timescale.com/
2. 註冊/登錄帳戶
3. 點擊 **Create Service**
4. 選擇配置：
   - **Region**: `us-east-1` (與 AWS 相同)
   - **Compute**: 最小配置 (0.5 CPU / 2GB RAM, ~$30/月)
   - **Storage**: 10GB 起步
5. 記錄連接信息：
   ```
   Host: xxx.tsdb.cloud.timescale.com
   Port: 5432
   Database: tsdb
   Username: tsdbadmin
   Password: (創建時設置)
   ```

### 步驟 2：運行數據庫遷移

在 TimescaleDB Cloud 控制台的 **SQL Editor** 中：
1. 打開 `infra/init.sql`
2. 複製全部內容
3. 粘貼到 SQL Editor 並執行

或使用命令行 (如果有 psql):
```bash
PGPASSWORD=你的密碼 psql -h xxx.tsdb.cloud.timescale.com -p 5432 -U tsdbadmin -d tsdb -f infra/init.sql
```

### 步驟 3：配置 Terraform 變量

```powershell
cd C:\Projects\market-sensemaking\infra\terraform

# 複製示例配置
copy terraform.tfvars.example terraform.tfvars

# 編輯 terraform.tfvars，填入 TimescaleDB Cloud 連接信息
notepad terraform.tfvars
```

terraform.tfvars 內容：
```hcl
use_timescaledb_cloud = true
timescaledb_host     = "xxx.tsdb.cloud.timescale.com"
timescaledb_port     = "5432"
timescaledb_name     = "tsdb"
timescaledb_user     = "tsdbadmin"
timescaledb_password = "你的密碼"
```

### 步驟 4：應用 Terraform 更新

```powershell
cd C:\Projects\market-sensemaking\infra\terraform
terraform init
terraform apply
```

這會更新 ECS 任務定義，將數據庫連接指向 TimescaleDB Cloud。

### 步驟 5：重啟 ECS 服務

```powershell
# 重啟所有服務
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-api --force-new-deployment --region us-east-1
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-collector --force-new-deployment --region us-east-1
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-reactor --force-new-deployment --region us-east-1
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-tile-worker --force-new-deployment --region us-east-1
```

### 步驟 6：驗證

```powershell
# 檢查服務狀態
aws ecs describe-services --cluster market-sensemaking-cluster --services market-sensemaking-collector --query "services[0].deployments" --region us-east-1

# 查看 collector 日志
aws logs tail /ecs/market-sensemaking/collector --follow --region us-east-1
```

### 可選：刪除 RDS 節省費用

確認 TimescaleDB Cloud 運行正常後，可以刪除 RDS：
```powershell
# 在 Terraform 中註釋掉 RDS 相關資源，或手動刪除
aws rds delete-db-instance --db-instance-identifier market-sensemaking-db --skip-final-snapshot --region us-east-1
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

## CI/CD 部署流水線 (Phase 3)

### GitHub Actions Workflows
- `.github/workflows/ci.yml` - 測試 (單元測試、對抗性測試、安全測試)
- `.github/workflows/deploy.yml` - 自動部署到 AWS

### 部署流程
```
push to main → 測試 → 構建 Docker → 推送 ECR → 遷移數據庫 → 部署 ECS → 健康檢查
```

### 分支策略
| 分支 | 環境 | 自動部署 |
|------|------|----------|
| `main` | Production | ✅ |
| `staging` | Staging | ✅ |
| 其他 | - | ❌ (僅測試) |

### GitHub Secrets 配置 (必須)

在 GitHub 倉庫設置中添加以下 Secrets：

```
Settings → Secrets and variables → Actions → New repository secret
```

| Secret 名稱 | 說明 | 範例值 |
|-------------|------|--------|
| `AWS_ACCESS_KEY_ID` | AWS IAM Access Key | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM Secret Key | `wJalr...` |
| `TIMESCALEDB_HOST` | TimescaleDB 主機 | `xxx.tsdb.cloud.timescale.com` |
| `TIMESCALEDB_PORT` | TimescaleDB 端口 | `39785` |
| `TIMESCALEDB_NAME` | 數據庫名稱 | `tsdb` |
| `TIMESCALEDB_USER` | 數據庫用戶 | `tsdbadmin` |
| `TIMESCALEDB_PASSWORD` | 數據庫密碼 | `你的密碼` |

### 手動觸發部署

```
GitHub → Actions → Deploy to AWS → Run workflow → 選擇環境
```

### IAM 權限要求

部署用的 IAM 用戶需要以下權限：
- `ecr:GetAuthorizationToken`
- `ecr:BatchCheckLayerAvailability`
- `ecr:PutImage`
- `ecr:InitiateLayerUpload`
- `ecr:UploadLayerPart`
- `ecr:CompleteLayerUpload`
- `ecs:UpdateService`
- `ecs:DescribeServices`
- `logs:DescribeLogGroups`
