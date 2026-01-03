-- ============================================================================
-- Belief Reaction System - Database Schema v1.0
-- ============================================================================
--
-- 核心理念: "看存在没意义，看反应才有意义"
--
-- 4 张核心表:
--   1. markets - 市场元数据（从 Gamma API 同步）
--   2. book_bins - 订单簿时序数据（heatmap 原料）
--   3. shock_events - Shock 检测事件
--   4. reaction_events - 反应分类事件
--   5. belief_states - 信念状态变化历史
-- ============================================================================

-- 启用 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 1. markets - 市场元数据
-- ============================================================================
CREATE TABLE IF NOT EXISTS markets (
    condition_id    TEXT PRIMARY KEY,           -- Polymarket condition ID
    question        TEXT NOT NULL,              -- 市场问题
    slug            TEXT,                       -- URL slug
    yes_token_id    TEXT NOT NULL,              -- YES token ID
    no_token_id     TEXT NOT NULL,              -- NO token ID
    tick_size       NUMERIC(5,4) DEFAULT 0.01,  -- 价格精度
    active          BOOLEAN DEFAULT TRUE,
    closed          BOOLEAN DEFAULT FALSE,
    volume_24h      NUMERIC,
    liquidity       NUMERIC,
    end_date        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_markets_active ON markets(active, closed);
CREATE INDEX IF NOT EXISTS idx_markets_volume ON markets(volume_24h DESC NULLS LAST);

-- ============================================================================
-- 2. book_bins - 订单簿时序数据（Heatmap 原料）
-- ============================================================================
-- 这是最重要的表，存储订单簿的时间快照
-- 用于绘制热力图

CREATE TABLE IF NOT EXISTS book_bins (
    ts              TIMESTAMPTZ NOT NULL,       -- 时间戳
    token_id        TEXT NOT NULL,              -- Token ID
    side            TEXT NOT NULL,              -- 'bid' 或 'ask'
    price           NUMERIC(5,3) NOT NULL,      -- 价格（如 0.720）
    size            NUMERIC NOT NULL,           -- 当前聚合大小
    PRIMARY KEY (ts, token_id, side, price)
);

-- 转换为 TimescaleDB hypertable（时序优化）
SELECT create_hypertable('book_bins', 'ts', if_not_exists => TRUE);

-- 创建索引用于快速查询
CREATE INDEX IF NOT EXISTS idx_book_bins_token_ts ON book_bins(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_book_bins_price ON book_bins(token_id, side, price);

-- ============================================================================
-- 3. shock_events - Shock 检测事件
-- ============================================================================
-- 当价格层被显著冲击时记录

CREATE TABLE IF NOT EXISTS shock_events (
    shock_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL,       -- Shock 发生时间
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,      -- 被冲击的价格
    side            TEXT NOT NULL,              -- 'bid' 或 'ask'
    trade_volume    NUMERIC NOT NULL,           -- 冲击交易量
    liquidity_before NUMERIC NOT NULL,          -- 冲击前流动性
    trigger_type    TEXT NOT NULL,              -- 'volume' 或 'consecutive'

    CONSTRAINT valid_side CHECK (side IN ('bid', 'ask')),
    CONSTRAINT valid_trigger CHECK (trigger_type IN ('volume', 'consecutive'))
);

CREATE INDEX IF NOT EXISTS idx_shock_token_ts ON shock_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_shock_ts ON shock_events(ts DESC);

-- ============================================================================
-- 4. reaction_events - 反应分类事件
-- ============================================================================
-- Shock 后观察 20 秒窗口，分类为 6 种反应类型

CREATE TABLE IF NOT EXISTS reaction_events (
    reaction_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shock_id        UUID REFERENCES shock_events(shock_id),
    ts              TIMESTAMPTZ NOT NULL,       -- 分类完成时间
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,

    -- 反应类型（6 种）
    reaction_type   TEXT NOT NULL,

    -- 反应指标快照
    refill_ratio    NUMERIC,                    -- 补单比例
    time_to_refill_ms INTEGER,                  -- 补单时间（毫秒）
    min_liquidity   NUMERIC,                    -- 窗口内最低流动性
    max_liquidity   NUMERIC,                    -- 窗口内最高流动性
    price_shift     NUMERIC(5,3),               -- 价格锚点移动
    liquidity_before NUMERIC,                   -- 冲击前流动性（用于上下文）

    CONSTRAINT valid_reaction CHECK (reaction_type IN (
        'HOLD',     -- 防守：快速补单
        'DELAY',    -- 犹豫：部分/慢速补单
        'PULL',     -- 撤退：立即取消
        'VACUUM',   -- 真空：流动性完全消失
        'CHASE',    -- 追价：锚点移动
        'FAKE'      -- 诱导：冲击后反而加单
    ))
);

CREATE INDEX IF NOT EXISTS idx_reaction_token_ts ON reaction_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_type ON reaction_events(reaction_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_shock ON reaction_events(shock_id);

-- ============================================================================
-- 5. belief_states - 信念状态变化历史
-- ============================================================================
-- 状态机输出：STABLE → FRAGILE → CRACKING → BROKEN

CREATE TABLE IF NOT EXISTS belief_states (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    old_state       TEXT NOT NULL,
    new_state       TEXT NOT NULL,
    trigger_reaction_id UUID REFERENCES reaction_events(reaction_id),
    evidence        JSONB,                      -- 证据详情

    CONSTRAINT valid_states CHECK (
        old_state IN ('STABLE', 'FRAGILE', 'CRACKING', 'BROKEN') AND
        new_state IN ('STABLE', 'FRAGILE', 'CRACKING', 'BROKEN')
    )
);

CREATE INDEX IF NOT EXISTS idx_belief_token_ts ON belief_states(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_belief_state ON belief_states(new_state, ts DESC);

-- ============================================================================
-- 6. trade_ticks - 交易记录（用于 Shock 检测）
-- ============================================================================
-- 存储 last_trade_price 消息，用于 Shock 检测

CREATE TABLE IF NOT EXISTS trade_ticks (
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    size            NUMERIC NOT NULL,
    side            TEXT NOT NULL,              -- 'BUY' 或 'SELL'
    PRIMARY KEY (ts, token_id, price)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('trade_ticks', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_trade_token_ts ON trade_ticks(token_id, ts DESC);

-- ============================================================================
-- 视图：当前市场状态
-- ============================================================================
CREATE OR REPLACE VIEW current_belief_states AS
SELECT DISTINCT ON (token_id)
    token_id,
    new_state as current_state,
    ts as last_change,
    evidence
FROM belief_states
ORDER BY token_id, ts DESC;

-- ============================================================================
-- 说明
-- ============================================================================
--
-- 阈值参数（在代码中配置）:
--   SHOCK_TIME_WINDOW_MS = 2000      -- Shock 检测时间窗口
--   SHOCK_VOLUME_THRESHOLD = 0.35    -- 触发 Shock 的成交量比例
--   SHOCK_CONSECUTIVE_TRADES = 3     -- 连续成交触发
--   REACTION_WINDOW_MS = 20000       -- 反应观察窗口
--   HOLD_REFILL_THRESHOLD = 0.8      -- HOLD 分类的补单比例
--   HOLD_TIME_THRESHOLD_MS = 5000    -- HOLD 分类的补单时间
--   VACUUM_THRESHOLD = 0.05          -- VACUUM 分类的流动性阈值
--
-- 状态转移规则（确定性）:
--   BROKEN: 2+ 个关键价位出现 VACUUM
--   CRACKING: 任何关键价位出现 PULL 或 VACUUM
--   FRAGILE: HOLD 和 DELAY 混合出现
--   STABLE: 连续 3+ HOLD 或 2+ FAKE
-- ============================================================================
