"""
数据库优化脚本 - 为100+市场添加索引
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from utils.db import engine, get_session

def optimize_database():
    """添加索引以提升查询性能"""
    
    print("🔧 Optimizing database for 100+ markets...\n")
    
    optimizations = []
    
    with engine.connect() as conn:
        # 1. Markets 表索引
        print("📊 Adding indexes to 'markets' table...")
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_markets_volume 
                ON markets(volume_24h DESC)
            """))
            optimizations.append("✅ idx_markets_volume")
        except Exception as e:
            print(f"  ⚠️  {e}")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_markets_updated 
                ON markets(updated_at DESC)
            """))
            optimizations.append("✅ idx_markets_updated")
        except Exception as e:
            print(f"  ⚠️  {e}")
        
        # 2. Daily metrics 表索引
        print("\n📊 Adding indexes to 'daily_metrics' table...")
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_metrics_date 
                ON daily_metrics(date DESC)
            """))
            optimizations.append("✅ idx_metrics_date")
        except Exception as e:
            print(f"  ⚠️  {e}")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_metrics_status 
                ON daily_metrics(status)
            """))
            optimizations.append("✅ idx_metrics_status")
        except Exception as e:
            print(f"  ⚠️  {e}")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_metrics_token_date 
                ON daily_metrics(token_id, date DESC)
            """))
            optimizations.append("✅ idx_metrics_token_date")
        except Exception as e:
            print(f"  ⚠️  {e}")
        
        conn.commit()
    
    print(f"\n{'='*60}")
    print("Optimization Results:")
    print(f"{'='*60}")
    for opt in optimizations:
        print(opt)
    print(f"{'='*60}\n")
    
    # 分析表统计信息
    print("📈 Analyzing table statistics...\n")
    session = get_session()
    try:
        # 市场数量
        markets_count = session.execute(
            text("SELECT COUNT(*) FROM markets")
        ).scalar()
        print(f"Markets in DB: {markets_count}")
        
        # 指标数量
        metrics_count = session.execute(
            text("SELECT COUNT(*) FROM daily_metrics")
        ).scalar()
        print(f"Metrics records: {metrics_count}")
        
        # 最新数据日期
        latest_date = session.execute(
            text("SELECT MAX(date) FROM daily_metrics")
        ).scalar()
        print(f"Latest data: {latest_date}")
        
        # 数据库大小（PostgreSQL）
        try:
            db_size = session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            ).scalar()
            print(f"Database size: {db_size}")
        except:
            # SQLite fallback
            print("Database size: Check manually for SQLite")
        
    finally:
        session.close()
    
    print("\n✅ Database optimization completed!\n")

def check_performance():
    """检查查询性能"""
    print("\n🔍 Testing query performance...\n")
    
    session = get_session()
    
    import time
    
    # 测试1: 获取所有市场（最常用查询）
    start = time.time()
    result = session.execute(text("""
        SELECT 
            dm.token_id,
            m.title,
            dm.status,
            dm.ui,
            dm.cs,
            m.volume_24h
        FROM daily_metrics dm
        JOIN markets m ON dm.token_id = m.token_id
        WHERE dm.date = (SELECT MAX(date) FROM daily_metrics)
        ORDER BY m.volume_24h DESC
        LIMIT 100
    """)).fetchall()
    
    elapsed = time.time() - start
    print(f"Query 1 (Main page): {elapsed*1000:.2f}ms ({len(result)} rows)")
    
    # 测试2: 状态筛选
    start = time.time()
    result = session.execute(text("""
        SELECT COUNT(*) 
        FROM daily_metrics 
        WHERE status LIKE '%Informed%'
        AND date = (SELECT MAX(date) FROM daily_metrics)
    """)).scalar()
    
    elapsed = time.time() - start
    print(f"Query 2 (Filter by status): {elapsed*1000:.2f}ms ({result} rows)")
    
    session.close()
    
    print("\n✅ Performance check completed!\n")

if __name__ == "__main__":
    optimize_database()
    check_performance()
