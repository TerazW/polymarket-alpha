-- ============================================================================
-- Belief Reaction System - Database Schema v5.0
-- ============================================================================
--
-- 核心理念: "看存在没意义，看反应才有意义"
--
-- v5 改进 (Evidence Player):
--   1. alerts 表 - 告警存储
--   2. alert_history 表 - 告警操作历史
--   3. data_health 表 - 数据健康监控
--   4. heatmap_tiles 表 - 预计算 heatmap 瓦片缓存
--   5. 压缩策略 (compression policies)
--
-- v3-v4 基础:
--   1. 时间桶采样 (bucket_ts) 代替消息条数采样
--   2. raw_events 表用于 debug/replay
--   3. 更新反应类型 (添加 SWEEP, NO_IMPACT)
--   4. 更新领先事件类型 (添加 GRADUAL_THINNING)
--   5. 数据保留策略 (retention policies)
--   6. 降采样 (continuous aggregates)
--
-- 核心表:
--   1. markets - 市场元数据
--   2. raw_events - 原始 WS 消息 (短期保留)
--   3. book_bins - 订单簿时序数据 (250ms 时间桶)
--   4. trade_ticks - 成交记录
--   5. shock_events - Shock 检测事件
--   6. reaction_events - 反应分类事件
--   7. leading_events - 领先事件
--   8. belief_states - 信念状态变化
--   9. anchor_levels - 关键价位快照
--  10. alerts - 告警 (v5)
--  11. alert_history - 告警历史 (v5)
--  12. data_health - 数据健康 (v5)
--  13. heatmap_tiles - 瓦片缓存 (v5)
-- ============================================================================

-- 启用 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 1. markets - 市场元数据
-- ============================================================================
CREATE TABLE IF NOT EXISTS markets (
    condition_id    TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    slug            TEXT,
    yes_token_id    TEXT NOT NULL,
    no_token_id     TEXT NOT NULL,
    tick_size       NUMERIC(5,4) DEFAULT 0.01,
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
-- 2. raw_events - 原始 WebSocket 消息 (v3: 用于 debug/replay)
-- ============================================================================
-- 短期保留 (7 天)，用于数据校验和回放测试
CREATE TABLE IF NOT EXISTS raw_events (
    ts              TIMESTAMPTZ NOT NULL,       -- 服务器时间戳
    arrival_ts      TIMESTAMPTZ NOT NULL,       -- 客户端到达时间
    event_type      TEXT NOT NULL,              -- 'trade', 'book', 'price_change'
    token_id        TEXT NOT NULL,
    payload         JSONB NOT NULL,             -- 原始 JSON 消息
    hash            TEXT,                       -- 消息 hash (用于一致性检查)
    PRIMARY KEY (ts, token_id, event_type)
);

SELECT create_hypertable('raw_events', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_raw_token_ts ON raw_events(token_id, ts DESC);

-- ============================================================================
-- 3. book_bins - 订单簿时序数据 (v3: 250ms 时间桶)
-- ============================================================================
-- 严格按时间桶保存，不按消息条数
CREATE TABLE IF NOT EXISTS book_bins (
    bucket_ts       TIMESTAMPTZ NOT NULL,       -- v3: 时间桶 (floor(ts / 250ms))
    ts              TIMESTAMPTZ NOT NULL,       -- 原始时间戳
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,              -- 'bid' 或 'ask'
    price           NUMERIC(5,3) NOT NULL,
    size            NUMERIC NOT NULL,
    PRIMARY KEY (bucket_ts, token_id, side, price)
);

SELECT create_hypertable('book_bins', 'bucket_ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_book_bins_token_ts ON book_bins(token_id, bucket_ts DESC);
CREATE INDEX IF NOT EXISTS idx_book_bins_price ON book_bins(token_id, side, price);

-- ============================================================================
-- 4. trade_ticks - 成交记录
-- ============================================================================
CREATE TABLE IF NOT EXISTS trade_ticks (
    ts              TIMESTAMPTZ NOT NULL,       -- 服务器时间戳
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    size            NUMERIC NOT NULL,
    side            TEXT NOT NULL,              -- 'BUY' 或 'SELL'
    PRIMARY KEY (ts, token_id, price)
);

SELECT create_hypertable('trade_ticks', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_trade_token_ts ON trade_ticks(token_id, ts DESC);

-- ============================================================================
-- 5. shock_events - Shock 检测事件
-- ============================================================================
CREATE TABLE IF NOT EXISTS shock_events (
    shock_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,
    trade_volume    NUMERIC NOT NULL,
    liquidity_before NUMERIC NOT NULL,
    baseline_size   NUMERIC,                    -- v2: 中位数基准
    trigger_type    TEXT NOT NULL,

    CONSTRAINT valid_side CHECK (side IN ('bid', 'ask')),
    CONSTRAINT valid_trigger CHECK (trigger_type IN ('volume', 'consecutive'))
);

CREATE INDEX IF NOT EXISTS idx_shock_token_ts ON shock_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_shock_ts ON shock_events(ts DESC);

-- ============================================================================
-- 6. reaction_events - 反应分类事件 (v3: 添加 SWEEP, NO_IMPACT)
-- ============================================================================
CREATE TABLE IF NOT EXISTS reaction_events (
    reaction_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shock_id        UUID REFERENCES shock_events(shock_id),
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,

    -- 反应类型 (v3: 7 种)
    reaction_type   TEXT NOT NULL,
    window_type     TEXT DEFAULT 'SLOW',        -- v2: 'FAST' 或 'SLOW'

    -- 反应指标快照
    baseline_size   NUMERIC,                    -- v2: 基准深度
    refill_ratio    NUMERIC,
    drop_ratio      NUMERIC,                    -- v2: 下降比例
    time_to_refill_ms INTEGER,
    min_liquidity   NUMERIC,
    max_liquidity   NUMERIC,
    vacuum_duration_ms INTEGER,                 -- v2: 真空持续时间
    shift_ticks     INTEGER,                    -- v2: 价格偏移 ticks
    price_shift     NUMERIC(5,3),
    liquidity_before NUMERIC,

    CONSTRAINT valid_reaction_v3 CHECK (reaction_type IN (
        'VACUUM',     -- 1. 流动性真空
        'SWEEP',      -- 2. 多档被扫
        'CHASE',      -- 3. 追价迁移
        'PULL',       -- 4. 撤退取消
        'HOLD',       -- 5. 防守补单
        'DELAYED',    -- 6. 犹豫观望
        'NO_IMPACT'   -- 7. v3: 无意义冲击
    )),
    CONSTRAINT valid_window CHECK (window_type IN ('FAST', 'SLOW'))
);

CREATE INDEX IF NOT EXISTS idx_reaction_token_ts ON reaction_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_type ON reaction_events(reaction_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_shock ON reaction_events(shock_id);

-- ============================================================================
-- 7. leading_events - 领先事件 (v3: 添加 GRADUAL_THINNING)
-- ============================================================================
CREATE TABLE IF NOT EXISTS leading_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL,
    event_type      TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,

    -- 通用字段
    drop_ratio      NUMERIC,
    duration_ms     INTEGER,

    -- PRE_SHOCK_PULL 字段
    trade_volume_nearby NUMERIC,
    is_anchor       BOOLEAN DEFAULT FALSE,

    -- DEPTH_COLLAPSE 字段
    affected_levels INTEGER,
    time_std_ms     NUMERIC,

    -- v3: GRADUAL_THINNING 字段
    total_depth_before NUMERIC,
    total_depth_after NUMERIC,
    trade_driven_ratio NUMERIC,

    CONSTRAINT valid_leading_type_v3 CHECK (event_type IN (
        'PRE_SHOCK_PULL',
        'DEPTH_COLLAPSE',
        'GRADUAL_THINNING'   -- v3
    ))
);

CREATE INDEX IF NOT EXISTS idx_leading_token_ts ON leading_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_leading_type ON leading_events(event_type, ts DESC);

-- ============================================================================
-- 8. belief_states - 信念状态变化
-- ============================================================================
CREATE TABLE IF NOT EXISTS belief_states (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    old_state       TEXT NOT NULL,
    new_state       TEXT NOT NULL,
    trigger_reaction_id UUID REFERENCES reaction_events(reaction_id),
    evidence        JSONB,

    CONSTRAINT valid_states CHECK (
        old_state IN ('STABLE', 'FRAGILE', 'CRACKING', 'BROKEN') AND
        new_state IN ('STABLE', 'FRAGILE', 'CRACKING', 'BROKEN')
    )
);

CREATE INDEX IF NOT EXISTS idx_belief_token_ts ON belief_states(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_belief_state ON belief_states(new_state, ts DESC);

-- ============================================================================
-- 9. anchor_levels - 关键价位快照
-- ============================================================================
CREATE TABLE IF NOT EXISTS anchor_levels (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,
    peak_size       NUMERIC,
    persistence_seconds NUMERIC,
    anchor_score    NUMERIC,
    rank            INTEGER
);

CREATE INDEX IF NOT EXISTS idx_anchor_token_ts ON anchor_levels(token_id, ts DESC);

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
-- v3: 数据保留策略 (Retention Policies)
-- ============================================================================
-- raw_events: 7 天
SELECT add_retention_policy('raw_events', INTERVAL '7 days', if_not_exists => TRUE);

-- book_bins (250ms): 14 天
SELECT add_retention_policy('book_bins', INTERVAL '14 days', if_not_exists => TRUE);

-- trade_ticks: 14 天
SELECT add_retention_policy('trade_ticks', INTERVAL '14 days', if_not_exists => TRUE);

-- ============================================================================
-- v3: 降采样 Continuous Aggregates (250ms → 1s)
-- ============================================================================
-- book_bins 1 秒聚合 (保留 90 天)
CREATE MATERIALIZED VIEW IF NOT EXISTS book_bins_1s
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 second', bucket_ts) AS bucket_ts_1s,
    token_id,
    side,
    price,
    AVG(size) AS avg_size,
    MAX(size) AS max_size,
    MIN(size) AS min_size,
    LAST(size, bucket_ts) AS last_size
FROM book_bins
GROUP BY time_bucket('1 second', bucket_ts), token_id, side, price
WITH NO DATA;

-- 自动刷新策略
SELECT add_continuous_aggregate_policy('book_bins_1s',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- book_bins 1 分钟聚合 (永久保留)
CREATE MATERIALIZED VIEW IF NOT EXISTS book_bins_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', bucket_ts) AS bucket_ts_1m,
    token_id,
    side,
    price,
    AVG(size) AS avg_size,
    MAX(size) AS max_size,
    MIN(size) AS min_size,
    LAST(size, bucket_ts) AS last_size
FROM book_bins
GROUP BY time_bucket('1 minute', bucket_ts), token_id, side, price
WITH NO DATA;

SELECT add_continuous_aggregate_policy('book_bins_1m',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================================================
-- v3: 数据一致性检查函数
-- ============================================================================
-- 检查是否有数据缺口
CREATE OR REPLACE FUNCTION check_data_gaps(
    p_token_id TEXT,
    p_start_ts TIMESTAMPTZ,
    p_end_ts TIMESTAMPTZ,
    p_max_gap_ms INTEGER DEFAULT 1000
) RETURNS TABLE(
    gap_start TIMESTAMPTZ,
    gap_end TIMESTAMPTZ,
    gap_ms INTEGER
) AS $$
BEGIN
    RETURN QUERY
    WITH ordered_buckets AS (
        SELECT bucket_ts,
               LEAD(bucket_ts) OVER (ORDER BY bucket_ts) AS next_bucket_ts
        FROM book_bins
        WHERE token_id = p_token_id
          AND bucket_ts BETWEEN p_start_ts AND p_end_ts
    )
    SELECT
        bucket_ts AS gap_start,
        next_bucket_ts AS gap_end,
        EXTRACT(EPOCH FROM (next_bucket_ts - bucket_ts))::INTEGER * 1000 AS gap_ms
    FROM ordered_buckets
    WHERE next_bucket_ts - bucket_ts > make_interval(secs => p_max_gap_ms / 1000.0);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- v5: 10. alerts - 告警表
-- ============================================================================
DO $$ BEGIN
    CREATE TYPE alert_severity AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_status AS ENUM ('OPEN', 'ACKED', 'RESOLVED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS alerts (
    alert_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    severity        alert_severity NOT NULL,
    status          alert_status NOT NULL DEFAULT 'OPEN',
    alert_type      TEXT NOT NULL,           -- e.g., 'BELIEF_BROKEN', 'VACUUM_DETECTED'
    summary         TEXT NOT NULL,
    confidence      NUMERIC(5,2),            -- 0-100
    evidence_token  TEXT NOT NULL,           -- token_id for evidence lookup
    evidence_t0     BIGINT NOT NULL,         -- ms timestamp for evidence lookup
    payload         JSONB,                   -- additional context
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_token_ts ON alerts(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, ts DESC);

-- ============================================================================
-- v5: 11. alert_history - 告警操作历史
-- ============================================================================
CREATE TABLE IF NOT EXISTS alert_history (
    id              SERIAL PRIMARY KEY,
    alert_id        UUID REFERENCES alerts(alert_id),
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action          TEXT NOT NULL,           -- 'CREATE', 'ACK', 'RESOLVE', 'REOPEN'
    old_status      alert_status,
    new_status      alert_status NOT NULL,
    actor           TEXT,                    -- user/system identifier
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_history_alert ON alert_history(alert_id, ts DESC);

-- ============================================================================
-- v5: 12. data_health - 数据健康监控
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_health (
    ts                      TIMESTAMPTZ NOT NULL,
    token_id                TEXT NOT NULL,
    missing_bucket_ratio    NUMERIC(5,4),     -- 0-1, ratio of missing 250ms buckets
    rebuild_count           INTEGER DEFAULT 0,
    hash_mismatch_count     INTEGER DEFAULT 0,
    last_rebuild_ts         TIMESTAMPTZ,
    last_hash_mismatch_ts   TIMESTAMPTZ,
    PRIMARY KEY (ts, token_id)
);

SELECT create_hypertable('data_health', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_data_health_token ON data_health(token_id, ts DESC);

-- 数据健康保留策略: 90 天
SELECT add_retention_policy('data_health', INTERVAL '90 days', if_not_exists => TRUE);

-- ============================================================================
-- v5: 13. heatmap_tiles - 预计算瓦片缓存
-- ============================================================================
CREATE TABLE IF NOT EXISTS heatmap_tiles (
    tile_id         TEXT PRIMARY KEY,        -- "token_id:lod:t_start:band"
    token_id        TEXT NOT NULL,
    lod_ms          INTEGER NOT NULL,        -- 250, 1000, 5000
    tile_ms         INTEGER NOT NULL,        -- 5000, 10000, 15000
    band            TEXT NOT NULL,           -- 'FULL', 'BEST_5', 'BEST_10', 'BEST_20'
    t_start         BIGINT NOT NULL,         -- ms timestamp
    t_end           BIGINT NOT NULL,
    tick_size       NUMERIC(5,4) NOT NULL,
    price_min       NUMERIC(5,3) NOT NULL,
    price_max       NUMERIC(5,3) NOT NULL,
    rows            INTEGER NOT NULL,
    cols            INTEGER NOT NULL,
    encoding_dtype  TEXT DEFAULT 'uint16',
    encoding_layout TEXT DEFAULT 'row_major',
    encoding_scale  TEXT DEFAULT 'log1p_clip',
    clip_pctl       NUMERIC(4,2) DEFAULT 0.95,
    clip_value      NUMERIC,
    compression_algo TEXT DEFAULT 'zstd',
    compression_level INTEGER DEFAULT 3,
    payload         BYTEA NOT NULL,          -- compressed binary data
    checksum_algo   TEXT DEFAULT 'xxh3_64',
    checksum_value  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tiles_token_lod ON heatmap_tiles(token_id, lod_ms, t_start);
CREATE INDEX IF NOT EXISTS idx_tiles_range ON heatmap_tiles(token_id, t_start, t_end);

-- ============================================================================
-- v5: 压缩策略 (Compression Policies)
-- ============================================================================
-- raw_events 压缩 (1 小时后)
ALTER TABLE raw_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('raw_events', INTERVAL '1 hour', if_not_exists => TRUE);

-- book_bins 压缩 (6 小时后)
ALTER TABLE book_bins SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id,side',
    timescaledb.compress_orderby = 'bucket_ts DESC'
);
SELECT add_compression_policy('book_bins', INTERVAL '6 hours', if_not_exists => TRUE);

-- trade_ticks 压缩 (6 小时后)
ALTER TABLE trade_ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('trade_ticks', INTERVAL '6 hours', if_not_exists => TRUE);

-- data_health 压缩 (1 天后)
ALTER TABLE data_health SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('data_health', INTERVAL '1 day', if_not_exists => TRUE);

-- ============================================================================
-- 说明 (v5 更新)
-- ============================================================================
--
-- 反应类型优先级 (v3):
--   1. VACUUM   - 流动性真空 (最强信号)
--   2. SWEEP    - 多档被扫
--   3. CHASE    - 追价迁移
--   4. PULL     - 撤退取消
--   5. HOLD     - 防守补单
--   6. DELAYED  - 犹豫观望
--   7. NO_IMPACT - 无意义冲击 (drop < 15%)
--
-- 领先事件类型 (v3):
--   1. PRE_SHOCK_PULL   - 无成交撤退
--   2. DEPTH_COLLAPSE   - 多价位同步塌陷
--   3. GRADUAL_THINNING - 渐进撤退
--
-- 告警严重级别 (v5):
--   1. LOW      - 低优先级，信息性
--   2. MEDIUM   - 中优先级，需关注
--   3. HIGH     - 高优先级，需及时处理
--   4. CRITICAL - 紧急，需立即处理
--
-- 数据保留策略:
--   - raw_events:      7 天 (debug/replay)
--   - book_bins 250ms: 14 天
--   - trade_ticks:     30 天
--   - book_bins 1s:    90 天 (降采样)
--   - book_bins 1m:    永久
--   - data_health:     90 天
--   - events/states:   1 年
--   - alerts:          永久
--
-- 压缩策略 (v5):
--   - raw_events:   1 小时后压缩
--   - book_bins:    6 小时后压缩
--   - trade_ticks:  6 小时后压缩
--   - data_health:  1 天后压缩
--
-- Heatmap Tiles:
--   - LOD: 250ms (详细), 1s (中等), 5s (概览)
--   - 编码: uint16 log1p_clip
--   - 压缩: zstd level 3
--   - 校验: xxh3_64
--
-- 时间桶采样:
--   bucket_ts = time_bucket('250ms', ts)
--   所有 duration/速度计算基于 bucket_ts
-- ============================================================================
