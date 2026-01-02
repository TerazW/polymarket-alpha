"""
Database Configuration Module
Supports SQLite (local) and PostgreSQL (production)
"""
from pathlib import Path
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")

# If no environment variable, use local SQLite
if not DATABASE_URL:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DB_DIR = PROJECT_ROOT / "data"
    DB_FILE = DB_DIR / "market_sensemaking.db"
    DB_DIR.mkdir(exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_FILE}"
    print(f"[DB Config] Using local SQLite: {DB_FILE}")
else:
    # Render's PostgreSQL URL may start with postgres://, need to change to postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"[DB Config] Using PostgreSQL (production)")

# Determine database type
IS_POSTGRES = "postgresql" in DATABASE_URL
IS_SQLITE = "sqlite" in DATABASE_URL

# Create engine
engine_kwargs = {}
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, **engine_kwargs)

# Create Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class
Base = declarative_base()


def get_session():
    """Get database session"""
    return SessionLocal()


def init_db():
    """Initialize database (create all tables)"""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Markets table - includes closed, active, categories, event info fields
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS markets (
                token_id VARCHAR(100) PRIMARY KEY,
                market_id VARCHAR(100),
                title TEXT,
                description TEXT,
                category VARCHAR(50),
                categories TEXT,
                event_id VARCHAR(100),
                event_title TEXT,
                current_price DECIMAL(10,4),
                volume_24h DECIMAL(20,8),
                resolution_date TIMESTAMP,
                closed BOOLEAN DEFAULT FALSE,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Daily metrics table - COMPLETE SCHEMA with all fields
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                date DATE,
                
                -- Profile metrics
                va_high DECIMAL(10,4),
                va_low DECIMAL(10,4),
                band_width DECIMAL(10,6),
                poc DECIMAL(10,4),
                pomd DECIMAL(10,4),
                
                -- Uncertainty metrics
                ui DECIMAL(10,4),
                ecr DECIMAL(10,6),
                acr DECIMAL(10,6),
                cer DECIMAL(10,4),
                edge_zone BOOLEAN DEFAULT FALSE,
                
                -- Conviction metrics
                cs DECIMAL(10,4),
                ar DECIMAL(10,6),
                volume_delta DECIMAL(20,8),
                total_volume DECIMAL(20,8),
                trade_count INTEGER,
                
                -- Status
                status VARCHAR(50),
                impulse_tag VARCHAR(50),
                
                -- Context
                current_price DECIMAL(10,4),
                days_to_expiry INTEGER,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(token_id, date)
            )
        """))
        
        # Trade histogram table (legacy, kept for compatibility)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trade_histogram (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                date DATE,
                price_bucket DECIMAL(10,4),
                trade_count INTEGER,
                volume DECIMAL(20,8),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Daily histogram table (new, includes aggressor data for Market Profile)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_histogram (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                date DATE,
                price_bin DECIMAL(10,4),
                volume DECIMAL(20,8),
                aggressive_buy DECIMAL(20,8) DEFAULT 0,
                aggressive_sell DECIMAL(20,8) DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(token_id, date, price_bin)
            )
        """))
        
        # Status changes table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS status_changes (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                old_status VARCHAR(50),
                new_status VARCHAR(50),
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.commit()
    
    print(f"[DB] Database initialized successfully")


def migrate_schema():
    """
    Migrate database schema
    Add new fields to existing database and create new tables
    """
    from sqlalchemy import text
    
    print("\n[DB Migration] Starting schema migration...")
    
    with engine.connect() as conn:
        if IS_POSTGRES:
            # PostgreSQL: Use ADD COLUMN IF NOT EXISTS
            migrations = [
                # Markets table fields
                ("markets.closed", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS closed BOOLEAN DEFAULT FALSE"),
                ("markets.active", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE"),
                ("markets.categories", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS categories TEXT"),
                ("markets.event_id", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS event_id VARCHAR(100)"),
                ("markets.event_title", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS event_title TEXT"),
                
                # Daily metrics - Profile fields
                ("daily_metrics.band_width", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS band_width DECIMAL(10,6)"),
                ("daily_metrics.poc", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS poc DECIMAL(10,4)"),
                ("daily_metrics.pomd", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS pomd DECIMAL(10,4)"),
                
                # Daily metrics - Uncertainty fields
                ("daily_metrics.ecr", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS ecr DECIMAL(10,6)"),
                ("daily_metrics.acr", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS acr DECIMAL(10,6)"),
                ("daily_metrics.edge_zone", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS edge_zone BOOLEAN DEFAULT FALSE"),
                
                # Daily metrics - Conviction fields
                ("daily_metrics.ar", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS ar DECIMAL(10,6)"),
                ("daily_metrics.volume_delta", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS volume_delta DECIMAL(20,8)"),
                ("daily_metrics.total_volume", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS total_volume DECIMAL(20,8)"),
                ("daily_metrics.trade_count", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS trade_count INTEGER"),
                
                # Daily metrics - Status fields
                ("daily_metrics.impulse_tag", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS impulse_tag VARCHAR(50)"),
            ]
            
            for col_name, sql in migrations:
                try:
                    conn.execute(text(sql))
                    print(f"[DB Migration] ✅ {col_name} ready")
                except Exception as e:
                    print(f"[DB Migration] ⚠️ {col_name}: {e}")
            
            # Create daily_histogram table
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS daily_histogram (
                        id SERIAL PRIMARY KEY,
                        token_id VARCHAR(100),
                        date DATE,
                        price_bin DECIMAL(10,4),
                        volume DECIMAL(20,8),
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, date, price_bin)
                    )
                """))
                print("[DB Migration] ✅ daily_histogram table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ daily_histogram: {e}")
            
            # Create index for daily_histogram
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_daily_histogram_token_date 
                    ON daily_histogram(token_id, date)
                """))
                print("[DB Migration] ✅ daily_histogram index ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ daily_histogram index: {e}")
            
            # Create phase_histogram table (for Market Profile Evolution)
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS phase_histogram (
                        id SERIAL PRIMARY KEY,
                        token_id VARCHAR(100) NOT NULL,
                        phase_number INTEGER NOT NULL,
                        price_bin DECIMAL(10,4) NOT NULL,
                        volume DECIMAL(20,8) DEFAULT 0,
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, phase_number, price_bin)
                    )
                """))
                print("[DB Migration] ✅ phase_histogram table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ phase_histogram: {e}")
            
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_phase_histogram_token_phase 
                    ON phase_histogram(token_id, phase_number)
                """))
                print("[DB Migration] ✅ phase_histogram index ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ phase_histogram index: {e}")
            
            # Create WebSocket data tables
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS ws_trades_hourly (
                        id SERIAL PRIMARY KEY,
                        token_id VARCHAR(100),
                        hour TIMESTAMP,
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        volume_delta DECIMAL(20,8) DEFAULT 0,
                        total_volume DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        poc DECIMAL(10,4),
                        pomd DECIMAL(10,4),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, hour)
                    )
                """))
                print("[DB Migration] ✅ ws_trades_hourly table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ ws_trades_hourly: {e}")
            
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS ws_price_bins (
                        id SERIAL PRIMARY KEY,
                        token_id VARCHAR(100),
                        hour TIMESTAMP,
                        price_bin DECIMAL(10,4),
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        UNIQUE(token_id, hour, price_bin)
                    )
                """))
                print("[DB Migration] ✅ ws_price_bins table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ ws_price_bins: {e}")
            
            # Create indexes for WebSocket tables
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_ws_trades_token_hour 
                    ON ws_trades_hourly(token_id, hour)
                """))
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_ws_bins_token_hour 
                    ON ws_price_bins(token_id, hour)
                """))
                print("[DB Migration] ✅ WebSocket indexes ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ WebSocket indexes: {e}")
            
        else:
            # SQLite: Need to check if columns exist
            result = conn.execute(text("PRAGMA table_info(markets)")).fetchall()
            markets_columns = [row[1] for row in result]
            
            result2 = conn.execute(text("PRAGMA table_info(daily_metrics)")).fetchall()
            metrics_columns = [row[1] for row in result2]
            
            new_columns = [
                # Markets table
                ("markets", "closed", "ALTER TABLE markets ADD COLUMN closed BOOLEAN DEFAULT FALSE"),
                ("markets", "active", "ALTER TABLE markets ADD COLUMN active BOOLEAN DEFAULT TRUE"),
                ("markets", "categories", "ALTER TABLE markets ADD COLUMN categories TEXT"),
                ("markets", "event_id", "ALTER TABLE markets ADD COLUMN event_id VARCHAR(100)"),
                ("markets", "event_title", "ALTER TABLE markets ADD COLUMN event_title TEXT"),
                
                # Daily metrics - Profile
                ("daily_metrics", "band_width", "ALTER TABLE daily_metrics ADD COLUMN band_width DECIMAL(10,6)"),
                ("daily_metrics", "poc", "ALTER TABLE daily_metrics ADD COLUMN poc DECIMAL(10,4)"),
                ("daily_metrics", "pomd", "ALTER TABLE daily_metrics ADD COLUMN pomd DECIMAL(10,4)"),
                
                # Daily metrics - Uncertainty
                ("daily_metrics", "ecr", "ALTER TABLE daily_metrics ADD COLUMN ecr DECIMAL(10,6)"),
                ("daily_metrics", "acr", "ALTER TABLE daily_metrics ADD COLUMN acr DECIMAL(10,6)"),
                ("daily_metrics", "edge_zone", "ALTER TABLE daily_metrics ADD COLUMN edge_zone BOOLEAN DEFAULT FALSE"),
                
                # Daily metrics - Conviction
                ("daily_metrics", "ar", "ALTER TABLE daily_metrics ADD COLUMN ar DECIMAL(10,6)"),
                ("daily_metrics", "volume_delta", "ALTER TABLE daily_metrics ADD COLUMN volume_delta DECIMAL(20,8)"),
                ("daily_metrics", "total_volume", "ALTER TABLE daily_metrics ADD COLUMN total_volume DECIMAL(20,8)"),
                ("daily_metrics", "trade_count", "ALTER TABLE daily_metrics ADD COLUMN trade_count INTEGER"),
                
                # Daily metrics - Status
                ("daily_metrics", "impulse_tag", "ALTER TABLE daily_metrics ADD COLUMN impulse_tag VARCHAR(50)"),
            ]
            
            for table, col_name, sql in new_columns:
                existing = markets_columns if table == "markets" else metrics_columns
                if col_name not in existing:
                    try:
                        conn.execute(text(sql))
                        print(f"[DB Migration] ✅ Added {table}.{col_name}")
                    except Exception as e:
                        print(f"[DB Migration] ⚠️ {col_name}: {e}")
                else:
                    print(f"[DB Migration] ✅ {col_name} exists")
            
            # SQLite: Create daily_histogram table
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS daily_histogram (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_id VARCHAR(100),
                        date DATE,
                        price_bin DECIMAL(10,4),
                        volume DECIMAL(20,8),
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, date, price_bin)
                    )
                """))
                print("[DB Migration] ✅ daily_histogram table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ daily_histogram: {e}")
            
            # SQLite: Create phase_histogram table
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS phase_histogram (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_id VARCHAR(100) NOT NULL,
                        phase_number INTEGER NOT NULL,
                        price_bin DECIMAL(10,4) NOT NULL,
                        volume DECIMAL(20,8) DEFAULT 0,
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, phase_number, price_bin)
                    )
                """))
                print("[DB Migration] ✅ phase_histogram table ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ phase_histogram: {e}")
            
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_phase_histogram_token_phase 
                    ON phase_histogram(token_id, phase_number)
                """))
                print("[DB Migration] ✅ phase_histogram index ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ phase_histogram index: {e}")

        conn.commit()
    
    print("[DB Migration] Migration completed\n")


def get_date_7_days_ago_sql():
    """Return SQL for date 7 days ago, compatible with PostgreSQL and SQLite"""
    if IS_POSTGRES:
        return "(CURRENT_DATE - INTERVAL '7 days')::date"
    else:
        return "date('now', '-7 days')"


def get_interval_hours_sql(hours: int = 24):
    """Return SQL for time interval, compatible with PostgreSQL and SQLite"""
    if IS_POSTGRES:
        return f"(NOW() - INTERVAL '{hours} hours')"
    else:
        return f"datetime('now', '-{hours} hours')"