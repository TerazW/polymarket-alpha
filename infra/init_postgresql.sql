-- ============================================================================
-- Belief Reaction System - Database Schema (PostgreSQL Standard)
-- ============================================================================
--
-- This is a PostgreSQL-compatible version without TimescaleDB
-- For AWS RDS PostgreSQL deployment
--
-- ============================================================================

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
-- 2. raw_events - 原始 WebSocket 消息 (用于 debug/replay)
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_events (
    seq             BIGSERIAL,
    ts              TIMESTAMPTZ NOT NULL,
    arrival_ts      TIMESTAMPTZ NOT NULL,
    event_type      TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    payload         JSONB NOT NULL,
    hash            TEXT,
    PRIMARY KEY (ts, token_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_raw_token_ts ON raw_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_raw_seq ON raw_events(seq);

-- ============================================================================
-- 3. book_bins - 订单簿时序数据 (250ms 时间桶)
-- ============================================================================
CREATE TABLE IF NOT EXISTS book_bins (
    bucket_ts       TIMESTAMPTZ NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    size            NUMERIC NOT NULL,
    PRIMARY KEY (bucket_ts, token_id, side, price)
);

CREATE INDEX IF NOT EXISTS idx_book_bins_token_ts ON book_bins(token_id, bucket_ts DESC);
CREATE INDEX IF NOT EXISTS idx_book_bins_price ON book_bins(token_id, side, price);

-- ============================================================================
-- 4. trade_ticks - 成交记录
-- ============================================================================
CREATE TABLE IF NOT EXISTS trade_ticks (
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    size            NUMERIC NOT NULL,
    side            TEXT NOT NULL,
    PRIMARY KEY (ts, token_id, price)
);

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
    baseline_size   NUMERIC,
    trigger_type    TEXT NOT NULL,
    -- v5.3 provenance
    engine_version  TEXT,
    config_hash     TEXT,
    raw_event_seq_start BIGINT,
    raw_event_seq_end BIGINT,

    CONSTRAINT valid_side CHECK (side IN ('bid', 'ask')),
    CONSTRAINT valid_trigger CHECK (trigger_type IN ('volume', 'consecutive'))
);

CREATE INDEX IF NOT EXISTS idx_shock_token_ts ON shock_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_shock_ts ON shock_events(ts DESC);

-- ============================================================================
-- 6. reaction_events - 反应分类事件
-- ============================================================================
CREATE TABLE IF NOT EXISTS reaction_events (
    reaction_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shock_id        UUID REFERENCES shock_events(shock_id),
    ts              TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,
    reaction_type   TEXT NOT NULL,
    window_type     TEXT DEFAULT 'SLOW',
    baseline_size   NUMERIC,
    refill_ratio    NUMERIC,
    drop_ratio      NUMERIC,
    time_to_refill_ms INTEGER,
    min_liquidity   NUMERIC,
    max_liquidity   NUMERIC,
    vacuum_duration_ms INTEGER,
    shift_ticks     INTEGER,
    price_shift     NUMERIC(5,3),
    liquidity_before NUMERIC,
    -- v5.3 provenance
    engine_version  TEXT,
    config_hash     TEXT,
    raw_event_seq_start BIGINT,
    raw_event_seq_end BIGINT,

    CONSTRAINT valid_reaction_v3 CHECK (reaction_type IN (
        'VACUUM', 'SWEEP', 'CHASE', 'PULL', 'HOLD', 'DELAYED', 'NO_IMPACT'
    )),
    CONSTRAINT valid_window CHECK (window_type IN ('FAST', 'SLOW'))
);

CREATE INDEX IF NOT EXISTS idx_reaction_token_ts ON reaction_events(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_type ON reaction_events(reaction_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_shock ON reaction_events(shock_id);

-- ============================================================================
-- 7. leading_events - 领先事件
-- ============================================================================
CREATE TABLE IF NOT EXISTS leading_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL,
    event_type      TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(5,3) NOT NULL,
    side            TEXT NOT NULL,
    drop_ratio      NUMERIC,
    duration_ms     INTEGER,
    trade_volume_nearby NUMERIC,
    is_anchor       BOOLEAN DEFAULT FALSE,
    affected_levels INTEGER,
    time_std_ms     NUMERIC,
    total_depth_before NUMERIC,
    total_depth_after NUMERIC,
    trade_driven_ratio NUMERIC,
    -- v5.3 provenance
    engine_version  TEXT,
    config_hash     TEXT,
    raw_event_seq_start BIGINT,
    raw_event_seq_end BIGINT,

    CONSTRAINT valid_leading_type_v3 CHECK (event_type IN (
        'PRE_SHOCK_PULL', 'DEPTH_COLLAPSE', 'GRADUAL_THINNING'
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
    -- v5.3 provenance
    engine_version  TEXT,
    config_hash     TEXT,
    trigger_event_seq BIGINT,

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
-- 10. alerts - 告警表
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
    alert_type      TEXT NOT NULL,
    summary         TEXT NOT NULL,
    confidence      NUMERIC(5,2),
    evidence_token  TEXT NOT NULL,
    evidence_t0     BIGINT NOT NULL,
    payload         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_token_ts ON alerts(token_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, ts DESC);

-- ============================================================================
-- 11. alert_history - 告警操作历史
-- ============================================================================
CREATE TABLE IF NOT EXISTS alert_history (
    id              SERIAL PRIMARY KEY,
    alert_id        UUID REFERENCES alerts(alert_id),
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action          TEXT NOT NULL,
    old_status      alert_status,
    new_status      alert_status NOT NULL,
    actor           TEXT,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_history_alert ON alert_history(alert_id, ts DESC);

-- ============================================================================
-- 12. data_health - 数据健康监控
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_health (
    ts                      TIMESTAMPTZ NOT NULL,
    token_id                TEXT NOT NULL,
    missing_bucket_ratio    NUMERIC(5,4),
    rebuild_count           INTEGER DEFAULT 0,
    hash_mismatch_count     INTEGER DEFAULT 0,
    last_rebuild_ts         TIMESTAMPTZ,
    last_hash_mismatch_ts   TIMESTAMPTZ,
    PRIMARY KEY (ts, token_id)
);

CREATE INDEX IF NOT EXISTS idx_data_health_token ON data_health(token_id, ts DESC);

-- ============================================================================
-- 13. heatmap_tiles - 预计算瓦片缓存
-- ============================================================================
CREATE TABLE IF NOT EXISTS heatmap_tiles (
    tile_id         TEXT PRIMARY KEY,
    token_id        TEXT NOT NULL,
    lod_ms          INTEGER NOT NULL,
    tile_ms         INTEGER NOT NULL,
    band            TEXT NOT NULL,
    t_start         BIGINT NOT NULL,
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
    payload         BYTEA NOT NULL,
    checksum_algo   TEXT DEFAULT 'xxh3_64',
    checksum_value  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tiles_token_lod ON heatmap_tiles(token_id, lod_ms, t_start);
CREATE INDEX IF NOT EXISTS idx_tiles_range ON heatmap_tiles(token_id, t_start, t_end);

-- ============================================================================
-- 14. config_snapshots - v5.3 配置快照表
-- ============================================================================
CREATE TABLE IF NOT EXISTS config_snapshots (
    config_hash     TEXT PRIMARY KEY,
    engine_version  TEXT NOT NULL,
    config_json     JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

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
-- Done
-- ============================================================================
