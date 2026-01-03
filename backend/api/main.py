"""
Belief Reaction System - FastAPI Backend
启动命令: uvicorn backend.api.main:app --reload
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from typing import Optional

# 创建 FastAPI 应用
app = FastAPI(
    title="Belief Reaction System",
    description="人类信念反应感知系统 - 检测预测市场中的信念变化",
    version="0.1.0"
)

# 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 路由
# ============================================================================

@app.get("/")
def root():
    """首页 - 系统信息"""
    return {
        "name": "Belief Reaction System",
        "version": "0.1.0",
        "philosophy": "看存在没意义，看反应才有意义",
        "status": "running"
    }


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok"}


@app.get("/api/reaction-types")
def get_reaction_types():
    """获取 6 种反应类型"""
    return {
        "reaction_types": [
            {"code": "HOLD", "name": "防守", "meaning": "快速补单，信念坚定", "color": "#22c55e"},
            {"code": "DELAY", "name": "犹豫", "meaning": "部分/慢速补单，信念动摇", "color": "#eab308"},
            {"code": "PULL", "name": "撤退", "meaning": "立即取消，信念破裂", "color": "#a855f7"},
            {"code": "VACUUM", "name": "真空", "meaning": "流动性完全消失", "color": "#ef4444"},
            {"code": "CHASE", "name": "追价", "meaning": "锚点移动，信念重新定价", "color": "#06b6d4"},
            {"code": "FAKE", "name": "诱导", "meaning": "冲击后反而加单", "color": "#3b82f6"},
        ]
    }


@app.get("/api/belief-states")
def get_belief_states():
    """获取 4 种信念状态"""
    return {
        "belief_states": [
            {"code": "STABLE", "name": "稳定", "indicator": "🟢", "color": "#22c55e"},
            {"code": "FRAGILE", "name": "脆弱", "indicator": "🟡", "color": "#eab308"},
            {"code": "CRACKING", "name": "破裂中", "indicator": "🟠", "color": "#f97316"},
            {"code": "BROKEN", "name": "已崩溃", "indicator": "🔴", "color": "#ef4444"},
        ]
    }


@app.get("/api/config")
def get_config():
    """获取当前系统配置（阈值参数）"""
    from poc.config import (
        SHOCK_TIME_WINDOW_MS, SHOCK_VOLUME_THRESHOLD, SHOCK_CONSECUTIVE_TRADES,
        REACTION_WINDOW_MS, HOLD_REFILL_THRESHOLD, HOLD_TIME_THRESHOLD_MS,
        VACUUM_THRESHOLD, KEY_LEVELS_COUNT
    )
    return {
        "shock": {
            "time_window_ms": SHOCK_TIME_WINDOW_MS,
            "volume_threshold": SHOCK_VOLUME_THRESHOLD,
            "consecutive_trades": SHOCK_CONSECUTIVE_TRADES,
        },
        "reaction": {
            "window_ms": REACTION_WINDOW_MS,
            "hold_refill_threshold": HOLD_REFILL_THRESHOLD,
            "hold_time_threshold_ms": HOLD_TIME_THRESHOLD_MS,
            "vacuum_threshold": VACUUM_THRESHOLD,
        },
        "belief_state": {
            "key_levels_count": KEY_LEVELS_COUNT,
        }
    }


# ============================================================================
# 真实市场数据
# ============================================================================

@app.get("/api/markets")
async def get_markets(
    limit: int = Query(default=50, le=100, description="返回数量，最多100"),
    category: Optional[str] = Query(default=None, description="分类筛选")
):
    """
    获取 Polymarket 热门市场列表（按交易量排序）

    - **limit**: 返回数量，默认50，最多100
    - **category**: 可选分类筛选
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 调用 Gamma API 获取活跃市场
            params = {
                "closed": "false",
                "active": "true",
                "limit": limit,
                "order": "volume24hr",
                "ascending": "false"
            }

            response = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params=params
            )

            if response.status_code != 200:
                return {"error": f"Gamma API error: {response.status_code}", "markets": []}

            raw_markets = response.json()

            # 格式化返回数据
            markets = []
            for m in raw_markets:
                # 获取 token IDs
                tokens = m.get("clobTokenIds") or []
                yes_token = tokens[0] if len(tokens) > 0 else None
                no_token = tokens[1] if len(tokens) > 1 else None

                markets.append({
                    "condition_id": m.get("conditionId"),
                    "question": m.get("question"),
                    "slug": m.get("slug"),
                    "yes_token_id": yes_token,
                    "no_token_id": no_token,
                    "yes_price": m.get("outcomePrices", [None, None])[0],
                    "no_price": m.get("outcomePrices", [None, None])[1] if len(m.get("outcomePrices", [])) > 1 else None,
                    "volume_24h": m.get("volume24hr", 0),
                    "liquidity": m.get("liquidityClob", 0),
                    "end_date": m.get("endDate"),
                    "image": m.get("image"),
                })

            return {
                "count": len(markets),
                "markets": markets
            }

    except httpx.TimeoutException:
        return {"error": "Request timeout", "markets": []}
    except Exception as e:
        return {"error": str(e), "markets": []}


@app.get("/api/markets/{condition_id}")
async def get_market_detail(condition_id: str):
    """获取单个市场详情"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://gamma-api.polymarket.com/markets/{condition_id}"
            )

            if response.status_code != 200:
                return {"error": f"Market not found: {condition_id}"}

            m = response.json()

            tokens = m.get("clobTokenIds") or []

            return {
                "condition_id": m.get("conditionId"),
                "question": m.get("question"),
                "description": m.get("description"),
                "slug": m.get("slug"),
                "yes_token_id": tokens[0] if len(tokens) > 0 else None,
                "no_token_id": tokens[1] if len(tokens) > 1 else None,
                "yes_price": m.get("outcomePrices", [None])[0],
                "volume_24h": m.get("volume24hr", 0),
                "liquidity": m.get("liquidityClob", 0),
                "end_date": m.get("endDate"),
                "image": m.get("image"),
                "created_at": m.get("createdAt"),
            }

    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# 启动信息
# ============================================================================

@app.on_event("startup")
async def startup():
    print()
    print("=" * 50)
    print("  Belief Reaction System API")
    print("  看存在没意义，看反应才有意义")
    print("=" * 50)
    print()
    print("  API 文档: http://localhost:8000/docs")
    print("  健康检查: http://localhost:8000/health")
    print()
