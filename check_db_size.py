"""
数据库大小和使用量检查工具
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from utils.db import engine, get_session, DATABASE_URL
from pathlib import Path

def check_database_size():
    """检查数据库大小和使用情况"""
    
    print("=" * 70)
    print("📊 Database Storage Analysis")
    print("=" * 70)
    print()
    
    session = get_session()
    
    try:
        # 数据库类型
        is_postgres = "postgresql" in DATABASE_URL
        is_sqlite = "sqlite" in DATABASE_URL
        
        print(f"Database Type: {'PostgreSQL (Render)' if is_postgres else 'SQLite (Local)'}")
        print(f"Connection: {DATABASE_URL[:50]}...")
        print()
        
        # 1. 表记录统计
        print("-" * 70)
        print("📋 Table Record Counts")
        print("-" * 70)
        
        tables = ['markets', 'daily_metrics', 'trade_histogram', 'status_changes']
        total_records = 0
        
        for table in tables:
            try:
                count = session.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
                total_records += count
                print(f"{table:20s}: {count:>10,} records")
            except Exception as e:
                print(f"{table:20s}: Error - {e}")
        
        print(f"{'Total':20s}: {total_records:>10,} records")
        print()
        
        # 2. 市场统计
        print("-" * 70)
        print("🎯 Market Statistics")
        print("-" * 70)
        
        # 最新日期
        latest_date = session.execute(
            text("SELECT MAX(date) FROM daily_metrics")
        ).scalar()
        print(f"Latest data date: {latest_date}")
        
        # 状态分布
        print(f"\nStatus Distribution (latest):")
        status_dist = session.execute(text("""
            SELECT status, COUNT(*) as count
            FROM daily_metrics
            WHERE date = (SELECT MAX(date) FROM daily_metrics)
            GROUP BY status
            ORDER BY count DESC
        """)).fetchall()
        
        for status, count in status_dist:
            print(f"  {status:20s}: {count:>5}")
        
        # 交易量统计
        print(f"\nVolume Statistics:")
        volume_stats = session.execute(text("""
            SELECT 
                COUNT(*) as market_count,
                SUM(volume_24h) as total_volume,
                AVG(volume_24h) as avg_volume,
                MIN(volume_24h) as min_volume,
                MAX(volume_24h) as max_volume
            FROM markets
        """)).fetchone()
        
        if volume_stats:
            print(f"  Total markets: {volume_stats[0]}")
            print(f"  Total 24h volume: ${volume_stats[1]:,.0f}")
            print(f"  Average volume: ${volume_stats[2]:,.0f}")
            print(f"  Min volume: ${volume_stats[3]:,.0f}")
            print(f"  Max volume: ${volume_stats[4]:,.0f}")
        
        print()
        
        # 3. 数据库大小
        print("-" * 70)
        print("💾 Storage Usage")
        print("-" * 70)
        
        if is_postgres:
            # PostgreSQL - 表大小
            table_sizes = session.execute(text("""
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                    pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
                FROM pg_tables
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """)).fetchall()
            
            total_bytes = 0
            for schema, table, size_pretty, size_bytes in table_sizes:
                print(f"{table:20s}: {size_pretty:>10}")
                total_bytes += size_bytes
            
            print(f"{'Total table size':20s}: {format_bytes(total_bytes):>10}")
            
            # 数据库总大小
            db_size = session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            ).scalar()
            print(f"\nDatabase total size: {db_size}")
            
            # 计算使用百分比（假设 1GB 限制）
            db_size_bytes = session.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar()
            
            one_gb = 1024 * 1024 * 1024
            usage_percent = (db_size_bytes / one_gb) * 100
            
            print(f"Free tier usage: {usage_percent:.2f}% of 1 GB")
            
            # 剩余空间
            remaining_gb = (one_gb - db_size_bytes) / (1024**3)
            print(f"Remaining space: {remaining_gb:.3f} GB")
            
            # 预估可存储市场数
            if total_records > 0:
                avg_bytes_per_market = total_bytes / session.execute(
                    text('SELECT COUNT(*) FROM markets')
                ).scalar()
                estimated_markets = remaining_gb * 1024**3 / avg_bytes_per_market
                print(f"\nEstimated additional markets capacity: ~{estimated_markets:,.0f}")
        
        elif is_sqlite:
            # SQLite - 文件大小
            db_path = DATABASE_URL.replace('sqlite:///', '')
            if os.path.exists(db_path):
                db_size_bytes = os.path.getsize(db_path)
                print(f"Database file size: {format_bytes(db_size_bytes)}")
                
                one_gb = 1024 * 1024 * 1024
                usage_percent = (db_size_bytes / one_gb) * 100
                print(f"Usage (vs 1GB): {usage_percent:.4f}%")
        
        print()
        
        # 4. 历史数据统计
        print("-" * 70)
        print("📅 Historical Data Coverage")
        print("-" * 70)
        
        date_range = session.execute(text("""
            SELECT 
                MIN(date) as earliest,
                MAX(date) as latest,
                COUNT(DISTINCT date) as day_count,
                COUNT(DISTINCT token_id) as unique_markets
            FROM daily_metrics
        """)).fetchone()
        
        if date_range and date_range[0]:
            print(f"Earliest data: {date_range[0]}")
            print(f"Latest data: {date_range[1]}")
            print(f"Days of data: {date_range[2]}")
            print(f"Unique markets tracked: {date_range[3]}")
            
            # 计算平均每天存储的市场数
            avg_markets_per_day = total_records / max(date_range[2], 1)
            print(f"Average metrics per day: {avg_markets_per_day:.0f}")
        
        print()
        
        # 5. 建议
        print("-" * 70)
        print("💡 Recommendations")
        print("-" * 70)
        
        if is_postgres:
            if usage_percent < 10:
                print("✅ Storage usage is low. Safe to expand to 500+ markets.")
            elif usage_percent < 50:
                print("✅ Storage usage is healthy. Can handle 200-500 markets.")
            elif usage_percent < 80:
                print("⚠️  Storage usage moderate. Monitor carefully. Max ~150 markets.")
            else:
                print("❌ Storage usage high! Consider:")
                print("   - Cleaning old historical data")
                print("   - Upgrading to paid plan")
                print("   - Reducing number of tracked markets")
        
        # 数据清理建议（兼容 SQLite 和 PostgreSQL）
        try:
            if is_postgres:
                old_data_query = text("""
                    SELECT COUNT(*) FROM daily_metrics
                    WHERE date < (CURRENT_DATE - INTERVAL '60 days')
                """)
            else:
                # SQLite 语法
                old_data_query = text("""
                    SELECT COUNT(*) FROM daily_metrics
                    WHERE date < date('now', '-60 days')
                """)
            
            old_data_count = session.execute(old_data_query).scalar()
            
            if old_data_count > 0:
                print(f"\n💡 Found {old_data_count} metrics older than 60 days")
                print("   Consider running: python cleanup_old_data.py")
        except Exception as e:
            # 如果查询失败，跳过这个检查
            pass
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        session.close()
    
    print()
    print("=" * 70)
    print("✅ Analysis Complete")
    print("=" * 70)
    print()

def format_bytes(bytes_val):
    """格式化字节数为可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"

if __name__ == "__main__":
    check_database_size()