-- ============================================================================
-- v5.35: Add Event Relationship to Markets
-- ============================================================================
--
-- Adds event_id and event metadata to enable event-level aggregation.
-- In Polymarket, events contain multiple markets (e.g., "Who will be nominated"
-- has many candidate markets).
--
-- Usage:
--   psql -d belief_reaction -f v5.35_add_event_relationship.sql
-- ============================================================================

-- Add event columns to markets table
ALTER TABLE markets
    ADD COLUMN IF NOT EXISTS event_id TEXT,
    ADD COLUMN IF NOT EXISTS event_slug TEXT,
    ADD COLUMN IF NOT EXISTS event_title TEXT;

-- Add indexes for event queries
CREATE INDEX IF NOT EXISTS idx_markets_event_id ON markets(event_id);
CREATE INDEX IF NOT EXISTS idx_markets_event_slug ON markets(event_slug);

-- Add comments
COMMENT ON COLUMN markets.event_id IS 'Polymarket event ID (groups related markets)';
COMMENT ON COLUMN markets.event_slug IS 'URL-friendly event identifier';
COMMENT ON COLUMN markets.event_title IS 'Event title/question (e.g., "Who will be nominated?")';

-- ============================================================================
-- Events summary view (read-only aggregation)
-- ============================================================================
CREATE OR REPLACE VIEW events_summary AS
SELECT
    m.event_id,
    m.event_slug,
    m.event_title,
    COUNT(*) as market_count,
    COUNT(DISTINCT m.yes_token_id) + COUNT(DISTINCT m.no_token_id) as token_count,
    SUM(m.volume_24h) as total_volume_24h,
    SUM(m.liquidity) as total_liquidity,
    MIN(m.created_at) as first_market_created,
    COUNT(CASE WHEN m.active = true AND m.closed = false THEN 1 END) as active_markets,
    COUNT(CASE WHEN m.closed = true THEN 1 END) as closed_markets
FROM markets m
WHERE m.event_id IS NOT NULL
GROUP BY m.event_id, m.event_slug, m.event_title
ORDER BY total_volume_24h DESC NULLS LAST;

-- ============================================================================
-- Event belief state aggregation view
-- ============================================================================
CREATE OR REPLACE VIEW event_belief_states AS
WITH latest_states AS (
    SELECT DISTINCT ON (token_id)
        token_id,
        new_state,
        ts as state_ts
    FROM belief_states
    ORDER BY token_id, ts DESC
),
market_states AS (
    SELECT
        m.event_id,
        m.yes_token_id,
        m.no_token_id,
        COALESCE(ls_yes.new_state, 'STABLE') as yes_state,
        COALESCE(ls_no.new_state, 'STABLE') as no_state
    FROM markets m
    LEFT JOIN latest_states ls_yes ON ls_yes.token_id = m.yes_token_id
    LEFT JOIN latest_states ls_no ON ls_no.token_id = m.no_token_id
    WHERE m.event_id IS NOT NULL
      AND m.active = true
      AND m.closed = false
)
SELECT
    event_id,
    COUNT(*) as market_count,
    COUNT(CASE WHEN yes_state = 'BROKEN' OR no_state = 'BROKEN' THEN 1 END) as broken_count,
    COUNT(CASE WHEN yes_state = 'CRACKING' OR no_state = 'CRACKING' THEN 1 END) as cracking_count,
    COUNT(CASE WHEN yes_state = 'FRAGILE' OR no_state = 'FRAGILE' THEN 1 END) as fragile_count,
    COUNT(CASE WHEN yes_state = 'STABLE' AND no_state = 'STABLE' THEN 1 END) as stable_count,
    -- Most severe state in event
    CASE
        WHEN COUNT(CASE WHEN yes_state = 'BROKEN' OR no_state = 'BROKEN' THEN 1 END) > 0 THEN 'BROKEN'
        WHEN COUNT(CASE WHEN yes_state = 'CRACKING' OR no_state = 'CRACKING' THEN 1 END) > 0 THEN 'CRACKING'
        WHEN COUNT(CASE WHEN yes_state = 'FRAGILE' OR no_state = 'FRAGILE' THEN 1 END) > 0 THEN 'FRAGILE'
        ELSE 'STABLE'
    END as worst_state
FROM market_states
GROUP BY event_id;

-- ============================================================================
-- Done
-- ============================================================================
