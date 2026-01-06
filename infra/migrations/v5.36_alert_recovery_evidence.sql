-- ============================================================================
-- v5.36: Alert Recovery Evidence and False Positive Tracking
-- ============================================================================
--
-- This migration adds:
-- 1. recovery_evidence - System-generated evidence for alert resolution
-- 2. is_false_positive - Flag for algorithm improvement
-- 3. false_positive_reason - Categorized reason for false positives
--
-- Per expert review: "告警不能只靠人工 resolve"
-- ============================================================================

-- Add recovery evidence column (array of strings)
ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS recovery_evidence TEXT[];

-- Add false positive tracking
ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS is_false_positive BOOLEAN DEFAULT FALSE;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS false_positive_reason TEXT;

-- Add resolved_by and resolved_at columns if not exist
ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS resolved_by TEXT;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS resolve_note TEXT;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS acked_at TIMESTAMPTZ;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS acked_by TEXT;

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS ack_note TEXT;

-- Create index on false positives for analysis
CREATE INDEX IF NOT EXISTS idx_alerts_false_positive
ON alerts(is_false_positive, false_positive_reason)
WHERE is_false_positive = TRUE;

-- Create view for false positive analysis (algorithm improvement)
CREATE OR REPLACE VIEW false_positive_analysis AS
SELECT
    false_positive_reason,
    alert_type,
    COUNT(*) as count,
    MIN(ts) as first_occurrence,
    MAX(ts) as last_occurrence,
    array_agg(DISTINCT token_id) as affected_tokens
FROM alerts
WHERE is_false_positive = TRUE
GROUP BY false_positive_reason, alert_type
ORDER BY count DESC;

-- Comment on new columns
COMMENT ON COLUMN alerts.recovery_evidence IS 'v5.36: System-generated evidence supporting resolution';
COMMENT ON COLUMN alerts.is_false_positive IS 'v5.36: Marked as false positive for algorithm improvement';
COMMENT ON COLUMN alerts.false_positive_reason IS 'v5.36: Reason category (THIN_MARKET, NOISE, MANIPULATION, STALE_DATA, THRESHOLD_TOO_SENSITIVE, OTHER)';

-- ============================================================================
-- Notes
-- ============================================================================
--
-- False positive reasons and their meanings:
--   THIN_MARKET - Low liquidity caused false trigger
--   NOISE - Random noise, not meaningful signal
--   MANIPULATION - Detected manipulation pattern
--   STALE_DATA - Data lag/staleness caused false trigger
--   THRESHOLD_TOO_SENSITIVE - Need to adjust thresholds
--   OTHER - Other reason (requires note)
--
-- Recovery evidence is generated automatically by the system when resolving
-- an alert. It includes:
--   - Current belief state
--   - State change timestamp
--   - Recent HOLD ratio
--   - Other relevant metrics
-- ============================================================================
