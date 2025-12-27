import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/market_sensemaking.db")

# 创建引擎
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    """初始化数据库（创建表）"""
    # 读取 schema.sql
    with open("schema.sql", "r") as f:
        schema = f.read()
    
    # 执行
    with engine.begin() as conn:
        # SQLite 需要分开执行每个语句
        statements = [s.strip() for s in schema.split(';') if s.strip()]
        for statement in statements:
            conn.execute(text(statement))
    
    print("✅ Database initialized")

def get_session():
    """获取数据库 session"""
    return SessionLocal()

# 测试
if __name__ == "__main__":
    # 确保 data 文件夹存在
    os.makedirs("data", exist_ok=True)
    
    # 初始化数据库
    init_db()
    
    # 测试连接
    session = get_session()
    result = session.execute(text("SELECT 1")).fetchone()
    print(f"Database connection test: {result}")
    session.close()