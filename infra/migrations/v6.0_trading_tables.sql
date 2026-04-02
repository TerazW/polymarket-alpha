-- v6.0: Trading Engine Tables
-- Adds tables for autonomous trading: positions, orders, PnL, signals

-- Trading positions
CREATE TABLE IF NOT EXISTS trading_positions (
    id BIGSERIAL PRIMARY KEY,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION,
    size_usd DOUBLE PRECISION NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'SETTLED')),
    pnl DOUBLE PRECISION,
    correlation_group TEXT,
    -- Signal snapshot at entry
    entry_direction DOUBLE PRECISION,
    entry_p_estimate DOUBLE PRECISION,
    entry_regime TEXT,
    entry_vpin DOUBLE PRECISION,
    entry_belief_state TEXT,
    entry_confidence DOUBLE PRECISION,
    -- Risk context
    bankroll_at_entry DOUBLE PRECISION,
    kelly_fraction DOUBLE PRECISION,
    drawdown_at_entry DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_market_id ON trading_positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON trading_positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_entry_time ON trading_positions(entry_time);

-- Trading orders
CREATE TABLE IF NOT EXISTS trading_orders (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT UNIQUE NOT NULL,
    position_id BIGINT REFERENCES trading_positions(id),
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    price DOUBLE PRECISION NOT NULL,
    size_usd DOUBLE PRECISION NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'GTC',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'LIVE', 'MATCHED', 'CANCELLED', 'REJECTED')),
    size_matched DOUBLE PRECISION DEFAULT 0,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    error_message TEXT,
    is_paper BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_orders_token_id ON trading_orders(token_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON trading_orders(status);

-- PnL tracking (daily snapshots)
CREATE TABLE IF NOT EXISTS trading_pnl_daily (
    date DATE NOT NULL,
    bankroll DOUBLE PRECISION NOT NULL,
    daily_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    cumulative_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    num_trades INT NOT NULL DEFAULT 0,
    num_wins INT NOT NULL DEFAULT 0,
    max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
    peak_bankroll DOUBLE PRECISION NOT NULL,
    -- Risk metrics
    avg_position_size DOUBLE PRECISION,
    max_position_size DOUBLE PRECISION,
    total_exposure DOUBLE PRECISION,
    -- Signal quality
    avg_edge DOUBLE PRECISION,
    avg_confidence DOUBLE PRECISION,
    regime_distribution JSONB,
    PRIMARY KEY (date)
);

-- Signal snapshots (for analysis and model improvement)
CREATE TABLE IF NOT EXISTS trading_signals (
    id BIGSERIAL,
    token_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    -- Probability & direction
    p_estimate DOUBLE PRECISION,
    p_confidence DOUBLE PRECISION,
    direction DOUBLE PRECISION,
    direction_strength DOUBLE PRECISION,
    -- Regime
    regime TEXT,
    regime_prob DOUBLE PRECISION,
    -- Changepoint
    changepoint_prob DOUBLE PRECISION,
    run_length DOUBLE PRECISION,
    -- Flow
    vpin DOUBLE PRECISION,
    -- Microstructure
    ofi_zscore DOUBLE PRECISION,
    depth_imbalance DOUBLE PRECISION,
    kyle_lambda DOUBLE PRECISION,
    -- Hawkes
    buy_intensity DOUBLE PRECISION,
    sell_intensity DOUBLE PRECISION,
    -- Belief state
    belief_state TEXT,
    -- Market context
    market_price DOUBLE PRECISION,
    -- Expert weights
    expert_weights JSONB,
    -- Whether a trade was taken on this signal
    trade_taken BOOLEAN DEFAULT FALSE,
    -- Realized outcome (filled in later)
    realized_return DOUBLE PRECISION
);

-- Convert to hypertable if TimescaleDB available
SELECT create_hypertable('trading_signals', 'timestamp',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Retention: keep signals for 90 days
SELECT add_retention_policy('trading_signals', INTERVAL '90 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_signals_token_time ON trading_signals(token_id, timestamp DESC);

-- Model performance tracking
CREATE TABLE IF NOT EXISTS trading_model_performance (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    model_name TEXT NOT NULL,
    -- Prediction quality
    hit_rate DOUBLE PRECISION,
    correlation DOUBLE PRECISION,
    log_loss DOUBLE PRECISION,
    -- Ensemble weight
    current_weight DOUBLE PRECISION,
    -- Sample size
    n_predictions INT,
    UNIQUE(date, model_name)
);

-- Configuration snapshots (for reproducibility)
CREATE TABLE IF NOT EXISTS trading_config_snapshots (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config_hash TEXT NOT NULL,
    kelly_config JSONB NOT NULL,
    risk_config JSONB NOT NULL,
    alpha_config JSONB,
    notes TEXT
);
