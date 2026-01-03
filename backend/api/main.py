"""
Belief Reaction System - FastAPI Backend
启动命令: uvicorn backend.api.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
