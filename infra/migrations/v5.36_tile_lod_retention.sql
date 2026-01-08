-- v5.36: Tile LOD Retention Policy
-- Different retention periods for different Level of Detail (LOD)
--
-- Strategy:
-- - 250ms LOD: 48 hours (high resolution, high volume)
-- - 1s LOD: 14 days (medium resolution)
-- - 5s LOD: 180 days (low resolution, long-term)
--
-- "高分辨率短期保留，低分辨率长期保留"

-- =============================================================================
-- Step 1: Add LOD column to heatmap_tiles if not exists
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'heatmap_tiles' AND column_name = 'lod_ms'
    ) THEN
        ALTER TABLE heatmap_tiles ADD COLUMN lod_ms INTEGER DEFAULT 250;
        COMMENT ON COLUMN heatmap_tiles.lod_ms IS 'Level of detail in milliseconds (250, 1000, 5000)';
    END IF;
END $$;

-- =============================================================================
-- Step 2: Create partitioned views for different LODs
-- =============================================================================

-- View for 250ms tiles (high resolution)
CREATE OR REPLACE VIEW heatmap_tiles_250ms AS
SELECT * FROM heatmap_tiles WHERE lod_ms = 250;

-- View for 1s tiles (medium resolution)
CREATE OR REPLACE VIEW heatmap_tiles_1s AS
SELECT * FROM heatmap_tiles WHERE lod_ms = 1000;

-- View for 5s tiles (low resolution)
CREATE OR REPLACE VIEW heatmap_tiles_5s AS
SELECT * FROM heatmap_tiles WHERE lod_ms = 5000;

-- =============================================================================
-- Step 3: Create retention policies per LOD
-- =============================================================================

-- Note: TimescaleDB retention policies are on the base hypertable.
-- For per-LOD retention, we use a custom cleanup function.

-- Custom retention function for LOD-based cleanup
CREATE OR REPLACE FUNCTION cleanup_tiles_by_lod()
RETURNS INTEGER AS $$
DECLARE
    deleted_250ms INTEGER;
    deleted_1s INTEGER;
    deleted_5s INTEGER;
    total_deleted INTEGER;
BEGIN
    -- 250ms tiles: keep 48 hours
    DELETE FROM heatmap_tiles
    WHERE lod_ms = 250
    AND t_start < (EXTRACT(EPOCH FROM NOW()) * 1000 - 48 * 3600 * 1000)::BIGINT;
    GET DIAGNOSTICS deleted_250ms = ROW_COUNT;

    -- 1s tiles: keep 14 days
    DELETE FROM heatmap_tiles
    WHERE lod_ms = 1000
    AND t_start < (EXTRACT(EPOCH FROM NOW()) * 1000 - 14 * 24 * 3600 * 1000)::BIGINT;
    GET DIAGNOSTICS deleted_1s = ROW_COUNT;

    -- 5s tiles: keep 180 days
    DELETE FROM heatmap_tiles
    WHERE lod_ms = 5000
    AND t_start < (EXTRACT(EPOCH FROM NOW()) * 1000 - 180 * 24 * 3600 * 1000)::BIGINT;
    GET DIAGNOSTICS deleted_5s = ROW_COUNT;

    total_deleted := deleted_250ms + deleted_1s + deleted_5s;

    RAISE NOTICE 'Tile cleanup: 250ms=%, 1s=%, 5s=%, total=%',
        deleted_250ms, deleted_1s, deleted_5s, total_deleted;

    RETURN total_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_tiles_by_lod() IS
'v5.36: LOD-based tile retention cleanup. Run periodically via cron or pg_cron.
250ms: 48h, 1s: 14d, 5s: 180d';

-- =============================================================================
-- Step 4: Create index for efficient LOD-based queries
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_heatmap_tiles_lod_time
ON heatmap_tiles (lod_ms, t_start DESC);

-- =============================================================================
-- Step 5: Statistics view for monitoring
-- =============================================================================

CREATE OR REPLACE VIEW tile_retention_stats AS
SELECT
    lod_ms,
    COUNT(*) as tile_count,
    MIN(t_start) as oldest_tile_ts,
    MAX(t_start) as newest_tile_ts,
    pg_size_pretty(SUM(pg_column_size(payload_b64))) as estimated_size,
    CASE lod_ms
        WHEN 250 THEN '48 hours'
        WHEN 1000 THEN '14 days'
        WHEN 5000 THEN '180 days'
        ELSE 'unknown'
    END as retention_policy
FROM heatmap_tiles
GROUP BY lod_ms
ORDER BY lod_ms;

COMMENT ON VIEW tile_retention_stats IS
'v5.36: Tile storage statistics by LOD level';

-- =============================================================================
-- Step 6: Schedule cleanup (if pg_cron is available)
-- =============================================================================

-- Uncomment if pg_cron extension is installed:
-- SELECT cron.schedule('tile-lod-cleanup', '0 */6 * * *', 'SELECT cleanup_tiles_by_lod()');

-- =============================================================================
-- Migration verification
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'v5.36 Tile LOD Retention Policy migration complete';
    RAISE NOTICE 'Retention policies: 250ms=48h, 1s=14d, 5s=180d';
    RAISE NOTICE 'Run cleanup_tiles_by_lod() periodically to enforce retention';
END $$;
