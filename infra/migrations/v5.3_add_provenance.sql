-- ============================================================================
-- v5.3 Migration: Add Provenance and Version Fields
-- ============================================================================
--
-- ChatGPT Audit 建议: Evidence 可审计性
--   1. engine_version: 引擎版本号
--   2. config_hash: 配置文件 hash (确保可重现)
--   3. raw_event_seq: 原始事件序列号范围 (溯源)
--
-- 目的:
--   - 任何输出都可以追溯到原始数据
--   - 任何异常都可以定位到配置/版本变更
--   - Evidence 包可以被密码学验证
-- ============================================================================

-- ============================================================================
-- 1. 添加 engine_version 和 config_hash 到事件表
-- ============================================================================

-- shock_events
ALTER TABLE shock_events
    ADD COLUMN IF NOT EXISTS engine_version TEXT,
    ADD COLUMN IF NOT EXISTS config_hash TEXT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_start BIGINT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_end BIGINT;

COMMENT ON COLUMN shock_events.engine_version IS 'Collector engine version (e.g., v4.0.0)';
COMMENT ON COLUMN shock_events.config_hash IS 'MD5 hash of poc/config.py at runtime';
COMMENT ON COLUMN shock_events.raw_event_seq_start IS 'First raw_event sequence contributing to this shock';
COMMENT ON COLUMN shock_events.raw_event_seq_end IS 'Last raw_event sequence contributing to this shock';

-- reaction_events
ALTER TABLE reaction_events
    ADD COLUMN IF NOT EXISTS engine_version TEXT,
    ADD COLUMN IF NOT EXISTS config_hash TEXT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_start BIGINT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_end BIGINT;

COMMENT ON COLUMN reaction_events.engine_version IS 'Collector engine version';
COMMENT ON COLUMN reaction_events.config_hash IS 'MD5 hash of poc/config.py at runtime';
COMMENT ON COLUMN reaction_events.raw_event_seq_start IS 'First raw_event sequence in reaction window';
COMMENT ON COLUMN reaction_events.raw_event_seq_end IS 'Last raw_event sequence in reaction window';

-- leading_events
ALTER TABLE leading_events
    ADD COLUMN IF NOT EXISTS engine_version TEXT,
    ADD COLUMN IF NOT EXISTS config_hash TEXT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_start BIGINT,
    ADD COLUMN IF NOT EXISTS raw_event_seq_end BIGINT;

COMMENT ON COLUMN leading_events.engine_version IS 'Collector engine version';
COMMENT ON COLUMN leading_events.config_hash IS 'MD5 hash of poc/config.py at runtime';
COMMENT ON COLUMN leading_events.raw_event_seq_start IS 'First raw_event sequence in detection window';
COMMENT ON COLUMN leading_events.raw_event_seq_end IS 'Last raw_event sequence in detection window';

-- belief_states
ALTER TABLE belief_states
    ADD COLUMN IF NOT EXISTS engine_version TEXT,
    ADD COLUMN IF NOT EXISTS config_hash TEXT,
    ADD COLUMN IF NOT EXISTS trigger_event_seq BIGINT;

COMMENT ON COLUMN belief_states.engine_version IS 'Collector engine version';
COMMENT ON COLUMN belief_states.config_hash IS 'MD5 hash of poc/config.py at runtime';
COMMENT ON COLUMN belief_states.trigger_event_seq IS 'Sequence of the event that triggered this state change';

-- ============================================================================
-- 2. 添加 seq 序列号到 raw_events
-- ============================================================================
-- 使用自增序列号，不依赖时间戳，保证全局唯一递增

ALTER TABLE raw_events
    ADD COLUMN IF NOT EXISTS seq BIGSERIAL;

COMMENT ON COLUMN raw_events.seq IS 'Global monotonic sequence number for provenance tracking';

-- 创建索引加速溯源查询
CREATE INDEX IF NOT EXISTS idx_raw_events_seq ON raw_events(seq);
CREATE INDEX IF NOT EXISTS idx_raw_events_seq_range ON raw_events(token_id, seq);

-- ============================================================================
-- 3. 添加 evidence_hash 到 alerts (用于 bundle 验证)
-- ============================================================================
ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS evidence_hash TEXT;

COMMENT ON COLUMN alerts.evidence_hash IS 'xxHash of the evidence bundle at alert creation time';

-- ============================================================================
-- 4. 创建 config_snapshots 表 (保存配置历史)
-- ============================================================================
CREATE TABLE IF NOT EXISTS config_snapshots (
    config_hash     TEXT PRIMARY KEY,
    engine_version  TEXT NOT NULL,
    config_content  TEXT NOT NULL,           -- 完整配置文件内容
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE config_snapshots IS 'Historical snapshots of config.py for auditability';

-- ============================================================================
-- 5. 创建 evidence_bundles 表 (缓存 bundle hash)
-- ============================================================================
CREATE TABLE IF NOT EXISTS evidence_bundles (
    bundle_id       TEXT PRIMARY KEY,        -- "token_id:t0"
    token_id        TEXT NOT NULL,
    t0              BIGINT NOT NULL,
    window_from     BIGINT NOT NULL,
    window_to       BIGINT NOT NULL,
    bundle_hash     TEXT NOT NULL,           -- xxHash64 of bundle content
    shock_count     INTEGER DEFAULT 0,
    reaction_count  INTEGER DEFAULT 0,
    leading_count   INTEGER DEFAULT 0,
    state_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ             -- 可选: 缓存过期时间
);

CREATE INDEX IF NOT EXISTS idx_bundles_token_t0 ON evidence_bundles(token_id, t0);
CREATE INDEX IF NOT EXISTS idx_bundles_hash ON evidence_bundles(bundle_hash);

COMMENT ON TABLE evidence_bundles IS 'Cached evidence bundle hashes for verification';

-- ============================================================================
-- 说明
-- ============================================================================
--
-- 溯源流程:
--   raw_event.seq → shock_events.raw_event_seq_start/end → reaction_events → alerts
--
-- 验证流程:
--   1. 获取 evidence bundle
--   2. 计算 bundle_hash
--   3. 对比 evidence_bundles.bundle_hash
--   4. 检查 engine_version 和 config_hash 一致性
--
-- config_hash 计算:
--   hashlib.md5(open('poc/config.py').read().encode()).hexdigest()
--
-- bundle_hash 计算:
--   xxhash.xxh64(json.dumps(bundle, sort_keys=True)).hexdigest()
-- ============================================================================
