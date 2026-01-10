# Market Sensemaking - Claude 開發筆記

## 當前狀態 (2026-01-10)

**Phase 5: 生產驗證** - 正在進行中

### 已完成的修復
1. ✅ 移除所有 Mock Data (主頁面 + 詳情頁)
2. ✅ 修復硬編碼 72% 價格 → 使用 API 的 `market.last_price`
3. ✅ 修復 EQS 不一致 (Radar 65 vs 詳情頁 70) → Evidence API 現在返回 `evidence_quality`
4. ✅ 修復前端無限循環 (Date.now() in useEffect deps)
5. ✅ Radar API 過濾：只顯示有 `book_bins` 數據的市場
6. ✅ **v5.40: Bookmap 風格熱力圖修復** (2026-01-10)

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

### 當前問題：熱力圖顯示 "Generating tiles..."
**原因**: `book_bins` 表沒有這些市場的數據
- Collector 正在監控的市場：`21695138873211375451...`, `57761428076807364758...`
- 但 Radar 顯示的市場 token_id 不同

**解決方案**: 確認 Collector 配置，確保它監控的市場和 `markets` 表中的市場一致

## 分支
- 開發分支：`claude/initial-setup-xsnPm-phveT`

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
