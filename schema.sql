CREATE TABLE IF NOT EXISTS markets (
    token_id VARCHAR(100) PRIMARY KEY,
    market_id VARCHAR(100),
    title TEXT,
    current_price DECIMAL(10,4),
    volume_24h DECIMAL(20,8),
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    token_id VARCHAR(100),
    date DATE,
    ui DECIMAL(10,4),
    cer DECIMAL(10,4),
    cs DECIMAL(10,4),
    status VARCHAR(20),
    current_price DECIMAL(10,4),
    days_to_expiry INTEGER,
    va_high DECIMAL(10,4),
    va_low DECIMAL(10,4),
    PRIMARY KEY (token_id, date)
);