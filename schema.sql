-- Markets table
CREATE TABLE IF NOT EXISTS markets (
    token_id VARCHAR(100) PRIMARY KEY,
    market_id VARCHAR(100),
    title TEXT NOT NULL,
    description TEXT,
    category VARCHAR(50),
    current_price DECIMAL(10,4),
    volume_24h DECIMAL(20,8),
    resolution_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trades (aggregated as histogram)
CREATE TABLE IF NOT EXISTS trade_histogram (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id VARCHAR(100) NOT NULL,
    period VARCHAR(10) NOT NULL,  -- '24h' or '7d'
    price_bin DECIMAL(10,4) NOT NULL,
    volume DECIMAL(20,8) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(token_id, period, price_bin)
);

-- Daily metrics
CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    ui DECIMAL(10,4),
    cer DECIMAL(10,4),
    cs DECIMAL(10,4),
    status VARCHAR(20),
    va_low DECIMAL(10,4),
    va_high DECIMAL(10,4),
    poc DECIMAL(10,4),
    current_price DECIMAL(10,4),
    days_to_expiry INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(token_id, date)
);

-- Status changes
CREATE TABLE IF NOT EXISTS status_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    ui_at_change DECIMAL(10,4),
    cer_at_change DECIMAL(10,4),
    cs_at_change DECIMAL(10,4)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_token_date ON daily_metrics(token_id, date);
CREATE INDEX IF NOT EXISTS idx_histogram_token ON trade_histogram(token_id, period);
CREATE INDEX IF NOT EXISTS idx_status_changes ON status_changes(token_id, timestamp);