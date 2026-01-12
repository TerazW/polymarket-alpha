# Market Sensemaking - Claude 開發筆記

## 當前狀態 (2026-01-12)

**Phase 5: 生產驗證** - 正在進行中

### 已完成的修復
1. ✅ 移除所有 Mock Data (主頁面 + 詳情頁)
2. ✅ 修復硬編碼 72% 價格 → 使用 API 的 `market.last_price`
3. ✅ 修復 EQS 不一致 (Radar 65 vs 詳情頁 70) → Evidence API 現在返回 `evidence_quality`
4. ✅ 修復前端無限循環 (Date.now() in useEffect deps)
5. ✅ Radar API 過濾：只顯示有 `book_bins` 數據的市場
6. ✅ **v5.40: Bookmap 風格熱力圖修復** (2026-01-10)
7. ✅ **v5.42: Collector 市場元數據同步** (2026-01-10)
8. ✅ **CI/CD 分支策略設置** (2026-01-12) - 限制 workflow 只在 dev/main 觸發
9. ✅ **Event Tape 時間窗口修復** (2026-01-12) - 從 90秒 擴大到 31分鐘
10. ✅ **v5.43: Heatmap 價格對齊修復** (2026-01-12) - 修復 tile 數據全為 0 的問題

### v5.40 Heatmap 修復詳情
**問題**: 熱力圖顯示「上下紅綠地毯」效果，不是 Bookmap 風格

**根本原因**:
- 前端用 `midPrice` 判斷顏色（價格 > midPrice → 紅色，< midPrice → 綠色）
- 這是語義錯誤：Bookmap 應根據 bid/ask side 決定顏色

**修復內容**:
1. **後端 API** (`backend/api/routes/v1.py`):
   - `/v1/heatmap/tiles` 現在返回 `bid_tiles` 和 `ask_tiles` 分開的數組
   - 使用 `side='bid'` 和 `side='ask'` 分別生成瓦片

2. **後端 Schema** (`backend/api/schemas/v1.py`):
   - `HeatmapTilesResponse` 改為 `bid_tiles` + `ask_tiles`

3. **前端 API 類型** (`frontend/src/lib/api.ts`):
   - 更新 `HeatmapTilesResponse` 接口

4. **前端渲染器** (`frontend/src/components/evidence/HeatmapRenderer.tsx`):
   - 接受 `bidTiles` 和 `askTiles` props
   - bid tiles → 綠色 (買方流動性)
   - ask tiles → 紅色 (賣方流動性)
   - 移除 `midPrice` 判斷邏輯
   - 使用 log 強度映射 + gamma 校正
   - 移除 `pixelated` 渲染，改用 `auto`
   - 添加 additive blending 平滑效果

5. **前端播放器** (`frontend/src/components/evidence/EvidencePlayer.tsx`):
   - 更新使用新的 tiles 結構

### 待部署
需要重新構建並部署 API 到 AWS：
```powershell
cd C:\Projects\market-sensemaking
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "821482074659.dkr.ecr.us-east-1.amazonaws.com"
docker build -t market-sensemaking-api -f infra/Dockerfile.api .
docker tag market-sensemaking-api:latest 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking/api:latest
docker push 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking/api:latest
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-api --force-new-deployment --region us-east-1
```

### v5.43 Heatmap 價格對齊修復 (2026-01-12)
**問題**: 熱力圖顯示「Waiting for data...」,tiles 數據全為 0

**根本原因**:
- `_build_matrix` 函數使用原始 `price_min` 構建 `price_to_row` 字典
- 但查詢價格時使用 tick 對齊後的值
- 如果 `price_min=0.653` (未對齊到 0.01 tick):
  - `price_to_row` keys: `{0.653, 0.663, 0.673, ...}`
  - 查詢時: `price_rounded = 0.65` (tick 對齊後)
  - 結果: lookup 失敗，所有數據被 skip

**修復內容**:
1. **`backend/heatmap/tile_generator.py`**:
   - `_build_matrix`: 在構建 `price_to_row` 前先對齊 `price_min/price_max`
   - `generate_tile`: 在創建 HeatmapTile 前對齊價格範圍
   - 添加更多 debug 日誌

**測試方式**:
部署後查看 API 日誌應顯示:
```
[MATRIX_DEBUG] Result: filled=N, skipped_side=0, skipped_col=M, skipped_price=0
[MATRIX_DEBUG] Matrix stats: nonzero=X, max=Y
```
其中 `filled > 0` 且 `skipped_price = 0`

### v5.42 Collector 市場元數據同步
**問題**: Radar 只顯示 2 個市場，但 Collector 監控 10 個

**根本原因**:
- Collector 將數據寫入 `book_bins` 表（使用 `token_id`）
- 但 `markets` 表沒有對應的市場元數據
- Radar API 用 `markets.yes_token_id` JOIN `book_bins.token_id`
- 7 個市場的 `token_id` 在 `book_bins` 中有數據，但在 `markets` 表中找不到對應記錄

**修復內容**:
1. **Polymarket API** (`utils/polymarket_api.py`):
   - `_extract_market_from_event()` 現在提取 `yes_token_id` 和 `no_token_id`
   - 從 `clobTokenIds` JSON 數組中提取兩個 token

2. **Collector** (`backend/collector/main.py`):
   - 新增 `save_markets_to_db()` 函數
   - 在 `get_top_markets()` 結束時自動同步市場到 `markets` 表
   - 使用 `ON CONFLICT DO UPDATE` 確保冪等性

## Git 分支策略 (2026-01-12)

### 分支結構
```
main        ← 生產穩定版本，push 會觸發 ECS 部署
  ↑
dev         ← 開發整合線，所有 PR 先合到這裡
  ↑
feat/*      ← 功能分支（短命）
fix/*       ← 修復分支（短命）
claude/*    ← Claude Code 會話分支（自動創建）
```

### 工作流程

**日常開發（你需要做的）**：
```powershell
# 1. 從 dev 開新分支
git checkout dev
git pull origin dev
git checkout -b fix/xxx-描述

# 2. 開發完成後推送
git push -u origin fix/xxx-描述

# 3. 去 GitHub 開 PR → dev
# CI 通過後 merge

# 4. 準備部署時
# 開 PR: dev → main
# merge 後自動部署到 ECS
```

**Claude Code 會話**：
- Claude Code 自動創建 `claude/xxx` 分支
- 完成後你需要手動：
  1. 把 claude 分支合到 dev：`git checkout dev && git merge origin/claude/xxx`
  2. 或開 PR

### CI/CD 觸發規則
| 動作 | CI | Deploy |
|------|-----|--------|
| push 到 feature/fix/claude 分支 | ❌ | ❌ |
| PR → dev | ✅ | ❌ |
| push → dev | ✅ | ❌ |
| push → main | ✅ | ✅ |
| 手動 workflow_dispatch | - | ✅ |

### 相關文件
- `.github/workflows/ci.yml` - CI 流程
- `.github/workflows/deploy.yml` - 部署流程
- `.github/workflows/language-check.yml` - 語言治理檢查

## AWS 部署狀態

### 帳戶信息
- AWS Account ID: `821482074659`
- Region: `us-east-1`
- Domain: `marketsensemaking.com` (Cloudflare DNS)
- API URL: `https://api.marketsensemaking.com`

### ECS 服務
- market-sensemaking-api
- market-sensemaking-collector
- market-sensemaking-reactor
- market-sensemaking-tile-worker

### ECR 倉庫
- `market-sensemaking/api`
- `market-sensemaking/collector`
- `market-sensemaking/reactor`
- `market-sensemaking/tile-worker`

## 本地項目路徑 (Windows)
```
C:\Projects\market-sensemaking
```

## 本地開發命令

### 安裝依賴
```powershell
# 後端
cd C:\Projects\market-sensemaking\backend
pip install -r requirements.txt

# 前端
cd C:\Projects\market-sensemaking\frontend
npm install
```

### 運行本地環境
```powershell
# 終端 1: 後端 API
cd C:\Projects\market-sensemaking\backend
python -m uvicorn api.main:app --reload --port 8000

# 終端 2: 前端
cd C:\Projects\market-sensemaking\frontend
npm run dev
```

### 本地環境 URL
- 前端: http://localhost:3000
- 後端: http://localhost:8000
- API 文檔: http://localhost:8000/docs

### 注意事項
- 前端默認連接生產 API (`https://api.marketsensemaking.com`)
- 要連接本地後端，需設置環境變量：
  ```powershell
  # frontend/.env.local
  NEXT_PUBLIC_API_URL=http://localhost:8000
  ```

## 構建命令模板
```powershell
# 1. 登入 ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "821482074659.dkr.ecr.us-east-1.amazonaws.com"

# 2. 構建 (在 C:\Projects\market-sensemaking 目錄下)
docker build -t market-sensemaking-api -f infra/Dockerfile.api .

# 3. 標記
docker tag market-sensemaking-api:latest 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking/api:latest

# 4. 推送
docker push 821482074659.dkr.ecr.us-east-1.amazonaws.com/market-sensemaking/api:latest

# 5. 更新 ECS
aws ecs update-service --cluster market-sensemaking-cluster --service market-sensemaking-api --force-new-deployment --region us-east-1
```

## 查看日誌
```powershell
# Collector 日誌
aws logs tail /ecs/market-sensemaking/collector --since 10m --region us-east-1

# API 日誌
aws logs tail /ecs/market-sensemaking/api --since 5m --region us-east-1
```

## Collector 配置
市場選擇配置在 `backend/common/config.py`:
- `MARKET_CATEGORY`: 默認 "politics"
- `MAX_MARKETS`: 默認 10
- `MIN_VOLUME_24H`: 默認 5000

## 重要文件
- `frontend/src/app/page.tsx` - 主頁面 (Radar)
- `frontend/src/app/market/[tokenId]/page.tsx` - 市場詳情頁
- `backend/api/routes/v1.py` - API 路由
- `backend/collector/main.py` - 數據收集器
- `backend/heatmap/tile_generator.py` - 熱力圖生成

## Phase 5 測試計劃
1. 驗證 5 個市場的數據流
2. 確認熱力圖正確顯示 (需要 book_bins 數據)
3. 確認 EQS 在所有頁面一致
4. 確認價格和狀態實時更新
