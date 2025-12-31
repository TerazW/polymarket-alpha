"""
数据库配置模块
支持 SQLite (本地) 和 PostgreSQL (生产环境)
"""
from pathlib import Path
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取数据库 URL
DATABASE_URL = os.getenv("DATABASE_URL")

# 如果没有设置环境变量，使用本地 SQLite
if not DATABASE_URL:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DB_DIR = PROJECT_ROOT / "data"
    DB_FILE = DB_DIR / "market_sensemaking.db"
    DB_DIR.mkdir(exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_FILE}"
    print(f"[DB Config] Using local SQLite: {DB_FILE}")
else:
    # Render 的 PostgreSQL URL 可能以 postgres:// 开头，需要改成 postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"[DB Config] Using PostgreSQL (production)")

# 判断数据库类型
IS_POSTGRES = "postgresql" in DATABASE_URL
IS_SQLITE = "sqlite" in DATABASE_URL

# 创建引擎
engine_kwargs = {}
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, **engine_kwargs)

# 创建 Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建 Base 类
Base = declarative_base()


def get_session():
    """获取数据库会话"""
    return SessionLocal()


def init_db():
    """初始化数据库（创建所有表）"""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Markets 表 - 包含 closed, active, categories 字段
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS markets (
                token_id VARCHAR(100) PRIMARY KEY,
                market_id VARCHAR(100),
                title TEXT,
                description TEXT,
                category VARCHAR(50),
                categories TEXT,
                current_price DECIMAL(10,4),
                volume_24h DECIMAL(20,8),
                resolution_date TIMESTAMP,
                closed BOOLEAN DEFAULT FALSE,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Daily metrics 表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                date DATE,
                ui DECIMAL(10,4),
                cer DECIMAL(10,4),
                cs DECIMAL(10,4),
                status VARCHAR(50),
                impulse_tag VARCHAR(50),
                edge_zone BOOLEAN DEFAULT FALSE,
                current_price DECIMAL(10,2),
                days_to_expiry INTEGER,
                va_high DECIMAL(10,2),
                va_low DECIMAL(10,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(token_id, date)
            )
        """))
        
        # Trade histogram 表 (旧版，保留兼容)
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
        
        # Daily histogram 表 (新版，包含 aggressor 数据，用于 Market Profile)
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
        
        # Status changes 表
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
    迁移数据库 schema
    为现有数据库添加新字段：closed, active, categories
    并创建 daily_histogram 表
    """
    from sqlalchemy import text
    
    print("\n[DB Migration] Starting schema migration...")
    
    with engine.connect() as conn:
        if IS_POSTGRES:
            # PostgreSQL: 使用 ADD COLUMN IF NOT EXISTS
            migrations = [
                ("closed", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS closed BOOLEAN DEFAULT FALSE"),
                ("active", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE"),
                ("categories", "ALTER TABLE markets ADD COLUMN IF NOT EXISTS categories TEXT"),
                # v5.3 新字段
                ("impulse_tag", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS impulse_tag VARCHAR(50)"),
                ("edge_zone", "ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS edge_zone BOOLEAN DEFAULT FALSE"),
            ]
            
            for col_name, sql in migrations:
                try:
                    conn.execute(text(sql))
                    print(f"[DB Migration] ✅ {col_name} column ready")
                except Exception as e:
                    print(f"[DB Migration] ⚠️ {col_name}: {e}")
            
            # 创建 daily_histogram 表（如果不存在）
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
            
            # 创建索引
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_daily_histogram_token_date 
                    ON daily_histogram(token_id, date)
                """))
                print("[DB Migration] ✅ daily_histogram index ready")
            except Exception as e:
                print(f"[DB Migration] ⚠️ daily_histogram index: {e}")
            
        else:
            # SQLite: 需要检查列是否存在
            result = conn.execute(text("PRAGMA table_info(markets)")).fetchall()
            markets_columns = [row[1] for row in result]
            
            result2 = conn.execute(text("PRAGMA table_info(daily_metrics)")).fetchall()
            metrics_columns = [row[1] for row in result2]
            
            new_columns = [
                ("markets", "closed", "ALTER TABLE markets ADD COLUMN closed BOOLEAN DEFAULT FALSE"),
                ("markets", "active", "ALTER TABLE markets ADD COLUMN active BOOLEAN DEFAULT TRUE"),
                ("markets", "categories", "ALTER TABLE markets ADD COLUMN categories TEXT"),
                # v5.3 新字段
                ("daily_metrics", "impulse_tag", "ALTER TABLE daily_metrics ADD COLUMN impulse_tag VARCHAR(50)"),
                ("daily_metrics", "edge_zone", "ALTER TABLE daily_metrics ADD COLUMN edge_zone BOOLEAN DEFAULT FALSE"),
            ]
            
            for table, col_name, sql in new_columns:
                existing = markets_columns if table == "markets" else metrics_columns
                if col_name not in existing:
                    try:
                        conn.execute(text(sql))
                        print(f"[DB Migration] ✅ Added {table}.{col_name} column")
                    except Exception as e:
                        print(f"[DB Migration] ⚠️ {col_name}: {e}")
                else:
                    print(f"[DB Migration] ✅ {col_name} column exists")
            
            # SQLite: 创建 daily_histogram 表
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
        
        conn.commit()
    
    print("[DB Migration] Migration completed\n")


def get_date_7_days_ago_sql():
    """返回兼容 PostgreSQL 和 SQLite 的 7 天前日期 SQL"""
    if IS_POSTGRES:
        return "(CURRENT_DATE - INTERVAL '7 days')::date"
    else:
        return "date('now', '-7 days')"


def get_interval_hours_sql(hours: int = 24):
    """返回兼容 PostgreSQL 和 SQLite 的时间间隔 SQL"""
    if IS_POSTGRES:
        return f"(NOW() - INTERVAL '{hours} hours')"
    else:
        return f"datetime('now', '-{hours} hours')"