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

# 创建引擎
engine_kwargs = {}
if "sqlite" in DATABASE_URL:
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
    
    # 创建表的 SQL（兼容 SQLite 和 PostgreSQL）
    with engine.connect() as conn:
        # Markets 表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS markets (
                token_id VARCHAR(100) PRIMARY KEY,
                market_id VARCHAR(100),
                title TEXT,
                description TEXT,
                category VARCHAR(50),
                current_price DECIMAL(10,4),
                volume_24h DECIMAL(20,8),
                resolution_date TIMESTAMP,
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
                current_price DECIMAL(10,2),
                days_to_expiry INTEGER,
                va_high DECIMAL(10,2),
                va_low DECIMAL(10,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(token_id, date)
            )
        """))
        
        # Trade histogram 表
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